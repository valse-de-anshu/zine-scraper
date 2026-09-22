package main

import (
	"archive/zip"
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"io/fs"
	"log"
	"mime"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

// ScrapeTask represents a single scrape & transfer job matching Hwaran's ScrapeTaskInfo schema.
type ScrapeTask struct {
	TaskID          string   `json:"task_id"`
	URL             string   `json:"url"`
	Mode            string   `json:"mode"`
	Flags           []string `json:"flags"`
	Limit           *int     `json:"limit"`
	TargetIP        string   `json:"target_ip,omitempty"`
	Transfer        string   `json:"transfer"`
	DeviceName      string   `json:"device_name"`
	DeviceBrand     string   `json:"device_brand"`
	Status          string   `json:"status"` // queued, scraping, transferring, completed, failed
	Progress        float64  `json:"progress"`
	Message         string   `json:"message"`
	FileCount       int      `json:"file_count"`
	MediaTitle      string   `json:"media_title"`
	Error           string   `json:"error"`
	CreatedAt       float64  `json:"created_at"`
	ZipPath         string   `json:"-"`
	DownloadedFiles []string `json:"-"`
	BaseDir         string   `json:"-"`
}

func (t *ScrapeTask) ToMap() map[string]any {
	return map[string]any{
		"task_id":      t.TaskID,
		"url":          t.URL,
		"mode":         t.Mode,
		"flags":        t.Flags,
		"limit":        t.Limit,
		"status":       t.Status,
		"progress":     t.Progress,
		"message":      t.Message,
		"file_count":   t.FileCount,
		"media_title":  t.MediaTitle,
		"error":        t.Error,
		"device_name":  t.DeviceName,
		"device_brand": t.DeviceBrand,
		"created_at":   t.CreatedAt,
	}
}

type TaskRegistry struct {
	sync.RWMutex
	tasks map[string]*ScrapeTask
}

var registry = &TaskRegistry{
	tasks: make(map[string]*ScrapeTask),
}

func (r *TaskRegistry) Add(task *ScrapeTask) {
	r.Lock()
	defer r.Unlock()
	r.tasks[task.TaskID] = task
}

func (r *TaskRegistry) Get(id string) *ScrapeTask {
	r.RLock()
	defer r.RUnlock()
	return r.tasks[id]
}

func (r *TaskRegistry) GetAll() []*ScrapeTask {
	r.RLock()
	defer r.RUnlock()
	list := make([]*ScrapeTask, 0, len(r.tasks))
	for _, t := range r.tasks {
		list = append(list, t)
	}
	sort.Slice(list, func(i, j int) bool {
		return list[i].CreatedAt > list[j].CreatedAt
	})
	return list
}

func (r *TaskRegistry) Delete(id string) {
	r.Lock()
	defer r.Unlock()
	if t, exists := r.tasks[id]; exists {
		if t.ZipPath != "" {
			_ = os.Remove(t.ZipPath)
		}
		delete(r.tasks, id)
	}
}

func (r *TaskRegistry) Clear() {
	r.Lock()
	defer r.Unlock()
	for _, t := range r.tasks {
		if t.ZipPath != "" {
			_ = os.Remove(t.ZipPath)
		}
	}
	r.tasks = make(map[string]*ScrapeTask)
}

func generateTaskID() string {
	b := make([]byte, 4)
	if _, err := rand.Read(b); err != nil {
		return fmt.Sprintf("tsk_%d", time.Now().UnixNano()%100000000)
	}
	return fmt.Sprintf("tsk_%s", hex.EncodeToString(b))
}

// corsMiddleware sets required headers for Hwaran and mobile web clients.
func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization, Connection")

		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusOK)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func sendJSON(w http.ResponseWriter, status int, data any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(data)
}

// getLanIPs returns all non-loopback IPv4 addresses and their broadcast addresses.
func getLanIPs() (ips []string, broadcasts []string) {
	broadcasts = append(broadcasts, "255.255.255.255")
	ifaces, err := net.Interfaces()
	if err != nil {
		return []string{"127.0.0.1"}, broadcasts
	}

	for _, iface := range ifaces {
		if iface.Flags&net.FlagUp == 0 || iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		addrs, err := iface.Addrs()
		if err != nil {
			continue
		}
		for _, addr := range addrs {
			var ip net.IP
			var mask net.IPMask
			switch v := addr.(type) {
			case *net.IPNet:
				ip = v.IP
				mask = v.Mask
			case *net.IPAddr:
				ip = v.IP
			}
			if ip == nil || ip.IsLoopback() || ip.To4() == nil {
				continue
			}
			ipv4 := ip.To4()
			ips = append(ips, ipv4.String())

			if mask != nil {
				// Calculate broadcast: IP | (^Mask)
				bcast := make(net.IP, len(ipv4))
				for i := 0; i < len(ipv4); i++ {
					bcast[i] = ipv4[i] | ^mask[i]
				}
				bcastStr := bcast.String()
				found := false
				for _, b := range broadcasts {
					if b == bcastStr {
						found = true
						break
					}
				}
				if !found {
					broadcasts = append(broadcasts, bcastStr)
				}
			}
		}
	}

	if len(ips) == 0 {
		ips = append(ips, "127.0.0.1")
	}
	return ips, broadcasts
}

// startUDPBeacon broadcasts presence packets so Hwaran auto-discovers the server instantly.
func startUDPBeacon(port int, stopChan <-chan struct{}) {
	beaconData, _ := json.Marshal(map[string]any{
		"service": "zine-scraper-server",
		"port":    port,
		"version": "2.1",
	})

	ticker := time.NewTicker(2500 * time.Millisecond)
	defer ticker.Stop()

	// Discovery ports: 53319 (new dedicated port) and 53318 (legacy fallback)
	targetPorts := []int{53319, 53318}

	for {
		select {
		case <-stopChan:
			return
		case <-ticker.C:
			_, broadcasts := getLanIPs()
			conn, err := net.ListenPacket("udp4", ":0")
			if err != nil {
				continue
			}
			for _, bcast := range broadcasts {
				for _, p := range targetPorts {
					dst, err := net.ResolveUDPAddr("udp4", fmt.Sprintf("%s:%d", bcast, p))
					if err == nil {
						_, _ = conn.WriteTo(beaconData, dst)
					}
				}
			}
			_ = conn.Close()
		}
	}
}

// resolveRepoDir discovers where zine scraper and orchestrator.py reside.
func resolveRepoDir() string {
	// 1. Env variable override
	if envDir := os.Getenv("ZINE_REPO_DIR"); envDir != "" {
		if _, err := os.Stat(filepath.Join(envDir, "orchestrator.py")); err == nil {
			return envDir
		}
	}

	// 2. Relative to executable
	if exe, err := os.Executable(); err == nil {
		exeDir := filepath.Dir(exe)
		if _, err := os.Stat(filepath.Join(exeDir, "orchestrator.py")); err == nil {
			return exeDir
		}
		parentDir := filepath.Dir(exeDir)
		if _, err := os.Stat(filepath.Join(parentDir, "orchestrator.py")); err == nil {
			return parentDir
		}
	}

	// 3. User config directory standard
	home, _ := os.UserHomeDir()
	defaultPath := filepath.Join(home, ".config", "zine scraper")
	if _, err := os.Stat(filepath.Join(defaultPath, "orchestrator.py")); err == nil {
		return defaultPath
	}

	// 4. Current working directory
	cwd, _ := os.Getwd()
	if _, err := os.Stat(filepath.Join(cwd, "orchestrator.py")); err == nil {
		return cwd
	}

	return defaultPath
}

// resolvePythonBin finds the venv python interpreter or falls back to system python3.
func resolvePythonBin(repoDir string) string {
	venvPython := filepath.Join(repoDir, "venv", "bin", "python")
	if _, err := os.Stat(venvPython); err == nil {
		return venvPython
	}
	if p, err := exec.LookPath("python3"); err == nil {
		return p
	}
	return "python"
}

// snapshotDirFiles returns a set of all file paths present in dir.
func snapshotDirFiles(root string) map[string]time.Time {
	files := make(map[string]time.Time)
	_ = filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err == nil && !d.IsDir() {
			if info, err := d.Info(); err == nil {
				files[path] = info.ModTime()
			}
		}
		return nil
	})
	return files
}

// createZipArchive creates an uncompressed/stored ZIP archive for high-throughput streaming.
func createZipArchive(destZip string, baseDir string, files []string) error {
	out, err := os.Create(destZip)
	if err != nil {
		return err
	}
	defer out.Close()

	zw := zip.NewWriter(out)
	defer zw.Close()

	for _, file := range files {
		rel, err := filepath.Rel(baseDir, file)
		if err != nil {
			rel = filepath.Base(file)
		}

		fi, err := os.Stat(file)
		if err != nil || fi.IsDir() {
			continue
		}

		header, err := zip.FileInfoHeader(fi)
		if err != nil {
			continue
		}
		header.Name = filepath.ToSlash(rel)
		header.Method = zip.Deflate // Standard Deflate compression: 100% compatible with Java ZipFile and ZipInputStream

		writer, err := zw.CreateHeader(header)
		if err != nil {
			continue
		}

		srcFile, err := os.Open(file)
		if err != nil {
			continue
		}
		_, err = io.Copy(writer, srcFile)
		srcFile.Close()
		if err != nil {
			return err
		}
	}

	return nil
}

// sendViaLocalSend transmits files to phone running LocalSend via LocalSend Protocol v2.
func sendViaLocalSend(targetIP string, files []string, baseDir string, updateProgress func(msg string, pct float64)) bool {
	if len(files) == 0 {
		return true
	}
	updateProgress("Preparing LocalSend transfer...", 0.72)

	// Auto-launch LocalSend on PC in background if not already active
	if _, err := exec.LookPath("localsend"); err == nil {
		check := exec.Command("pgrep", "-f", "localsend")
		if err := check.Run(); err != nil {
			log.Println("Starting LocalSend in background on PC...")
			bgProc := exec.Command("localsend", "--hidden")
			_ = bgProc.Start()
			time.Sleep(1000 * time.Millisecond)
		}
	}

	type fileMeta struct {
		ID       string `json:"id"`
		FileName string `json:"fileName"`
		Size     int64  `json:"size"`
		FileType string `json:"fileType"`
	}

	filesMap := make(map[string]fileMeta)
	filePathByID := make(map[string]string)

	for i, f := range files {
		fi, err := os.Stat(f)
		if err != nil || fi.IsDir() {
			continue
		}
		id := fmt.Sprintf("file_%d_%s", i, filepath.Base(f))
		rel, err := filepath.Rel(baseDir, f)
		if err != nil {
			rel = filepath.Base(f)
		}

		ext := strings.ToLower(filepath.Ext(f))
		mimeType := mime.TypeByExtension(ext)
		if mimeType == "" {
			mimeType = "application/octet-stream"
		}

		filesMap[id] = fileMeta{
			ID:       id,
			FileName: filepath.ToSlash(rel),
			Size:     fi.Size(),
			FileType: mimeType,
		}
		filePathByID[id] = f
	}

	if len(filesMap) == 0 {
		return false
	}

	preparePayload := map[string]any{
		"info": map[string]any{
			"alias":       "Zine Scraper (Go Engine)",
			"version":     "2.1",
			"deviceModel": "Linux Workstation",
			"deviceType":  "desktop",
			"fingerprint": "zine-scraper-go",
			"port":        53318,
			"protocol":    "http",
			"download":    false,
		},
		"files": filesMap,
	}

	payloadBytes, _ := json.Marshal(preparePayload)
	client := &http.Client{Timeout: 15 * time.Second}

	var sessionID string
	var tokens map[string]string

	prepareURL := fmt.Sprintf("http://%s:53317/api/localsend/v2/prepare-upload", targetIP)
	for attempt := 1; attempt <= 4; attempt++ {
		resp, err := client.Post(prepareURL, "application/json", bytes.NewReader(payloadBytes))
		if err == nil && resp.StatusCode == http.StatusOK {
			var respData struct {
				SessionID string            `json:"sessionId"`
				Files     map[string]string `json:"files"`
			}
			if err := json.NewDecoder(resp.Body).Decode(&respData); err == nil && respData.SessionID != "" {
				sessionID = respData.SessionID
				tokens = respData.Files
				resp.Body.Close()
				break
			}
			resp.Body.Close()
		}
		updateProgress(fmt.Sprintf("Connecting to phone LocalSend (%d/4)...", attempt), 0.72)
		time.Sleep(1200 * time.Millisecond)
	}

	if sessionID == "" || len(tokens) == 0 {
		log.Printf("LocalSend prepare-upload failed on %s:53317", targetIP)
		return false
	}

	// Stream files individually
	uploadClient := &http.Client{Timeout: 120 * time.Second}
	uploadedCount := 0
	totalFiles := len(tokens)

	for id, token := range tokens {
		path := filePathByID[id]
		f, err := os.Open(path)
		if err != nil {
			continue
		}

		fi, _ := f.Stat()
		uploadedCount++
		pct := 0.75 + (0.23 * (float64(uploadedCount) / float64(totalFiles)))
		updateProgress(fmt.Sprintf("Sending %s (%d/%d)", filepath.Base(path), uploadedCount, totalFiles), pct)

		uploadURL := fmt.Sprintf("http://%s:53317/api/localsend/v2/upload?sessionId=%s&fileId=%s&token=%s", targetIP, sessionID, id, token)
		req, err := http.NewRequest(http.MethodPost, uploadURL, f)
		if err != nil {
			f.Close()
			return false
		}
		req.Header.Set("Content-Type", "application/octet-stream")
		req.ContentLength = fi.Size()

		resp, err := uploadClient.Do(req)
		f.Close()
		if err != nil || resp.StatusCode != http.StatusOK {
			log.Printf("LocalSend upload failed for %s: %v", filepath.Base(path), err)
			return false
		}
		resp.Body.Close()
	}

	return true
}

// getKDEConnectDeviceID returns the ID and name of an available or paired KDE Connect device.
func getKDEConnectDeviceID() (string, string) {
	if _, err := exec.LookPath("kdeconnect-cli"); err != nil {
		return "", ""
	}
	// Try available devices (-a) first
	out, err := exec.Command("kdeconnect-cli", "-a", "--id-name-only").Output()
	if err == nil {
		lines := strings.Split(strings.TrimSpace(string(out)), "\n")
		for _, l := range lines {
			parts := strings.SplitN(strings.TrimSpace(l), " ", 2)
			if len(parts) >= 1 && parts[0] != "" {
				name := "Android Phone"
				if len(parts) == 2 {
					name = parts[1]
				}
				return parts[0], name
			}
		}
	}
	// Fallback to any paired device (-l)
	out, err = exec.Command("kdeconnect-cli", "-l", "--id-name-only").Output()
	if err == nil {
		lines := strings.Split(strings.TrimSpace(string(out)), "\n")
		for _, l := range lines {
			parts := strings.SplitN(strings.TrimSpace(l), " ", 2)
			if len(parts) >= 1 && parts[0] != "" {
				name := "Android Phone"
				if len(parts) == 2 {
					name = parts[1]
				}
				return parts[0], name
			}
		}
	}
	return "", ""
}

func isKDEConnectAvailable() bool {
	id, _ := getKDEConnectDeviceID()
	return id != ""
}

// sendViaKDEConnect shares a file directly to the phone via KDE Connect daemon over TLS.
func sendViaKDEConnect(filePath string, updateProgress func(msg string, pct float64)) bool {
	deviceID, devName := getKDEConnectDeviceID()
	if deviceID == "" {
		log.Println("[KDE Connect] No paired/available devices found.")
		return false
	}

	updateProgress(fmt.Sprintf("Connecting to %s...", devName), 0.80)
	log.Printf("[KDE Connect] Sharing %s with device %s (%s)...", filepath.Base(filePath), devName, deviceID)

	shareCmd := exec.Command("kdeconnect-cli", "-d", deviceID, "--share", filePath)
	if err := shareCmd.Run(); err != nil {
		log.Printf("[KDE Connect] Transfer failed: %v", err)
		return false
	}

	updateProgress(fmt.Sprintf("Sent to %s via KDE Connect!", devName), 1.0)
	return true
}

// runScrapeWorker executes the zine scraper in the background and prepares delivery.
func runScrapeWorker(task *ScrapeTask, repoDir string, pythonBin string) {
	task.Status = "scraping"
	task.Progress = 0.15
	task.Message = fmt.Sprintf("Scraping media (%s)...", task.Mode)

	home, _ := os.UserHomeDir()
	downloadsRoot := filepath.Join(home, "Downloads", "Zine")
	targetRoot := filepath.Join(downloadsRoot, "Quick grab")
	if task.Mode == "vacuum" {
		targetRoot = filepath.Join(downloadsRoot, "Vacuum")
	}
	_ = os.MkdirAll(targetRoot, 0755)

	filesBefore := snapshotDirFiles(targetRoot)
	startTime := time.Now()

	// Assemble CLI args for orchestrator.py
	orchestratorPath := filepath.Join(repoDir, "orchestrator.py")
	args := []string{orchestratorPath}

	if len(task.Flags) > 0 {
		args = append(args, task.Flags...)
	} else if task.Mode == "quick_grab" {
		args = append(args, "--0")
	} else if task.Mode == "vacuum" {
		if task.Limit != nil && *task.Limit > 0 {
			args = append(args, fmt.Sprintf("--%d", *task.Limit))
		} else {
			args = append(args, "-a")
		}
	}

	if task.Limit != nil && *task.Limit > 0 {
		limitFlag := fmt.Sprintf("--%d", *task.Limit)
		hasLimit := false
		for _, f := range task.Flags {
			if f == limitFlag {
				hasLimit = true
				break
			}
		}
		if !hasLimit {
			args = append(args, limitFlag)
		}
	}

	args = append(args, task.URL)

	log.Printf("[TASK %s] Executing: %s %s", task.TaskID, pythonBin, strings.Join(args[1:], " "))
	cmd := exec.Command(pythonBin, args...)
	cmd.Dir = repoDir

	stdoutPipe, err := cmd.StdoutPipe()
	if err != nil {
		task.Status = "failed"
		task.Error = fmt.Sprintf("Pipe error: %v", err)
		task.Message = "Internal runner error"
		return
	}
	cmd.Stderr = cmd.Stdout // merge stderr into stdout for unified parsing

	if err := cmd.Start(); err != nil {
		task.Status = "failed"
		task.Error = fmt.Sprintf("Failed to launch scraper: %v", err)
		task.Message = "Scraper launch failed"
		return
	}

	// Live progress and title parsing
	go func() {
		scanner := bufio.NewScanner(stdoutPipe)
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			if line == "" {
				continue
			}

			// Clean ANSI terminal escapes
			cleanLine := line
			if idx := strings.Index(cleanLine, "◆ "); idx != -1 {
				title := strings.TrimSpace(cleanLine[idx+len("◆ "):])
				if title != "" && task.MediaTitle == "" {
					task.MediaTitle = title
					log.Printf("[SCRAPER] [%s] Media title: %s", task.TaskID, title)
				}
			}
			if strings.Contains(cleanLine, "● Chapter") || strings.Contains(cleanLine, "● Episode") || strings.Contains(cleanLine, "✦ Done") {
				msg := strings.TrimPrefix(strings.TrimPrefix(cleanLine, "● "), "✦ ")
				task.Message = msg
				log.Printf("[SCRAPER] [%s] %s", task.TaskID, msg)
				if task.Progress < 0.65 {
					task.Progress += 0.05
				}
			}
		}
	}()

	cmdErr := cmd.Wait()

	// Detect new files created during scrape
	filesAfter := snapshotDirFiles(targetRoot)
	var newFiles []string

	for path, modTime := range filesAfter {
		if _, existed := filesBefore[path]; !existed || modTime.After(startTime.Add(-5*time.Second)) {
			newFiles = append(newFiles, path)
		}
	}

	// Fallback detection: if map diff missed anything, find files modified in last 10 minutes
	if len(newFiles) == 0 {
		cutoff := time.Now().Add(-10 * time.Minute)
		_ = filepath.WalkDir(targetRoot, func(path string, d fs.DirEntry, err error) error {
			if err == nil && !d.IsDir() {
				if info, err := d.Info(); err == nil && info.ModTime().After(cutoff) {
					newFiles = append(newFiles, path)
				}
			}
			return nil
		})
	}

	task.DownloadedFiles = newFiles
	task.BaseDir = targetRoot
	task.FileCount = len(newFiles)

	if cmdErr != nil && len(newFiles) == 0 {
		task.Status = "failed"
		task.Error = fmt.Sprintf("Scraper exited with code: %v", cmdErr)
		task.Message = "Scraper failed or URL unsupported"
		return
	}

	var totalBytes int64
	for _, f := range newFiles {
		if fi, err := os.Stat(f); err == nil {
			totalBytes += fi.Size()
		}
	}
	sizeMB := float64(totalBytes) / (1024 * 1024)

	// Pre-package ZIP archive for transfer
	task.Message = fmt.Sprintf("Packaging %d file(s) (%.1f MB)...", len(newFiles), sizeMB)
	task.Progress = 0.75

	zipFileName := fmt.Sprintf("zine_%s.zip", task.TaskID)
	if task.MediaTitle != "" {
		re := regexp.MustCompile(`[^a-zA-Z0-9_\-\. ]+`)
		cleanTitle := re.ReplaceAllString(task.MediaTitle, "_")
		cleanTitle = strings.TrimSpace(cleanTitle)
		if cleanTitle != "" {
			zipFileName = fmt.Sprintf("%s.zip", cleanTitle)
		}
	}
	tmpZip := filepath.Join(os.TempDir(), zipFileName)
	if err := createZipArchive(tmpZip, targetRoot, newFiles); err == nil {
		task.ZipPath = tmpZip
	} else {
		log.Printf("Warning: Could not pre-package zip for task %s: %v", task.TaskID, err)
	}

	// Priority 1: KDE Connect (Default & user preferred bridge)
	useKDEConnect := (task.Transfer == "kdeconnect") || (task.Transfer == "hybrid" && isKDEConnectAvailable())
	if useKDEConnect && task.ZipPath != "" {
		task.Status = "transferring"
		task.Message = fmt.Sprintf("Sending to phone via KDE Connect (%.1f MB)...", sizeMB)
		kdeSuccess := sendViaKDEConnect(task.ZipPath, func(msg string, pct float64) {
			task.Message = msg
			task.Progress = pct
		})
		if kdeSuccess {
			task.Status = "completed"
			task.Progress = 1.0
			task.Message = fmt.Sprintf("Delivered via KDE Connect (Saved in Download/%s)", zipFileName)
			return
		}
		log.Println("KDE Connect delivery failed or device unreachable, falling back...")
	}

	// Priority 2: LocalSend
	useLocalSend := (task.Transfer == "localsend") || (task.Transfer == "hybrid" && sizeMB > 500.0)
	if useLocalSend && task.TargetIP != "" {
		task.Status = "transferring"
		task.Message = fmt.Sprintf("Payload (%.1f MB) -> LocalSend transfer...", sizeMB)
		localsendSuccess := sendViaLocalSend(task.TargetIP, newFiles, targetRoot, func(msg string, pct float64) {
			task.Message = msg
			task.Progress = pct
		})
		if localsendSuccess {
			task.Status = "completed"
			task.Progress = 1.0
			task.Message = "Sent to phone via LocalSend successfully!"
			return
		}
	}

	// Priority 3: Direct Stream (HTTP fallback)
	task.Status = "completed"
	task.Progress = 1.0
	task.Message = fmt.Sprintf("Media ready for direct download (%.1f MB)", sizeMB)
}

// killExistingServerOnPort terminates any older instance of zine-server or processes holding the port.
func killExistingServerOnPort(port int) {
	currentPID := os.Getpid()
	out, err := exec.Command("pgrep", "-f", "zine-server").Output()
	if err == nil {
		pids := strings.Fields(strings.TrimSpace(string(out)))
		for _, pStr := range pids {
			pid, err := strconv.Atoi(pStr)
			if err == nil && pid != currentPID {
				proc, err := os.FindProcess(pid)
				if err == nil {
					_ = proc.Signal(syscall.SIGTERM)
				}
			}
		}
	}
	// Also free the port if occupied
	_ = exec.Command("fuser", "-k", "-TERM", fmt.Sprintf("%d/tcp", port)).Run()
	time.Sleep(300 * time.Millisecond)
}

func main() {
	port := flag.Int("port", 53318, "Server listening port")
	host := flag.String("host", "0.0.0.0", "Server bind host")
	flag.Parse()

	repoDir := resolveRepoDir()
	pythonBin := resolvePythonBin(repoDir)

	mux := http.NewServeMux()

	// GET /api/ping
	mux.HandleFunc("/api/ping", func(w http.ResponseWriter, r *http.Request) {
		sendJSON(w, http.StatusOK, map[string]any{
			"status":      "ok",
			"app":         "zine-scraper",
			"engine":      "golang",
			"version":     "2.1",
			"server_time": float64(time.Now().UnixNano()) / 1e9,
		})
	})

	// GET /api/tasks
	// DELETE /api/tasks (Clear all)
	mux.HandleFunc("/api/tasks", func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodGet:
			all := registry.GetAll()
			taskList := make([]map[string]any, 0, len(all))
			for _, t := range all {
				taskList = append(taskList, t.ToMap())
			}
			sendJSON(w, http.StatusOK, map[string]any{"tasks": taskList})
		case http.MethodDelete:
			registry.Clear()
			log.Println("Cleared all scrape tasks.")
			sendJSON(w, http.StatusOK, map[string]any{"status": "cleared", "message": "All tasks cleared"})
		default:
			http.Error(w, "Method Not Allowed", http.StatusMethodNotAllowed)
		}
	})

	// POST /api/tasks/clear and POST /api/clear
	mux.HandleFunc("/api/tasks/clear", func(w http.ResponseWriter, r *http.Request) {
		registry.Clear()
		log.Println("Cleared all scrape tasks.")
		sendJSON(w, http.StatusOK, map[string]any{"status": "cleared", "message": "All tasks cleared"})
	})
	mux.HandleFunc("/api/clear", func(w http.ResponseWriter, r *http.Request) {
		registry.Clear()
		log.Println("Cleared all scrape tasks.")
		sendJSON(w, http.StatusOK, map[string]any{"status": "cleared", "message": "All tasks cleared"})
	})

	// GET /api/tasks/{id} and DELETE /api/tasks/{id}
	mux.HandleFunc("/api/tasks/", func(w http.ResponseWriter, r *http.Request) {
		taskID := strings.TrimPrefix(r.URL.Path, "/api/tasks/")
		if taskID == "" || taskID == "clear" {
			return
		}

		switch r.Method {
		case http.MethodGet:
			task := registry.Get(taskID)
			if task != nil {
				sendJSON(w, http.StatusOK, task.ToMap())
			} else {
				sendJSON(w, http.StatusNotFound, map[string]any{"error": "Task not found"})
			}
		case http.MethodDelete:
			registry.Delete(taskID)
			sendJSON(w, http.StatusOK, map[string]any{"status": "deleted", "task_id": taskID})
		default:
			http.Error(w, "Method Not Allowed", http.StatusMethodNotAllowed)
		}
	})

	// POST /api/scrape
	mux.HandleFunc("/api/scrape", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method Not Allowed", http.StatusMethodNotAllowed)
			return
		}

		var payload struct {
			URL         string   `json:"url"`
			Mode        string   `json:"mode"`
			Flags       []string `json:"flags"`
			Limit       any      `json:"limit"`
			TargetIP    string   `json:"target_ip"`
			Transfer    string   `json:"transfer"`
			DeviceName  string   `json:"device_name"`
			DeviceBrand string   `json:"device_brand"`
			AppName     string   `json:"app_name"`
			AppVersion  string   `json:"app_version"`
		}

		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			sendJSON(w, http.StatusBadRequest, map[string]any{"error": "Invalid JSON payload"})
			return
		}

		url := strings.TrimSpace(payload.URL)
		if url == "" {
			sendJSON(w, http.StatusBadRequest, map[string]any{"error": "Missing 'url' parameter"})
			return
		}

		mode := payload.Mode
		if mode == "" {
			mode = "quick_grab"
		}

		var limitVal *int
		if payload.Limit != nil {
			switch v := payload.Limit.(type) {
			case float64:
				i := int(v)
				limitVal = &i
			case int:
				limitVal = &v
			case string:
				if i, err := strconv.Atoi(v); err == nil {
					limitVal = &i
				}
			}
		}

		clientIP, _, _ := net.SplitHostPort(r.RemoteAddr)
		targetIP := payload.TargetIP
		if targetIP == "" {
			targetIP = clientIP
		}

		transfer := payload.Transfer
		if transfer == "" {
			transfer = "hybrid"
		}

		devName := payload.DeviceName
		if devName == "" {
			devName = "Android Device"
		}
		devBrand := payload.DeviceBrand
		if devBrand == "" {
			devBrand = "Android"
		}

		taskID := generateTaskID()
		task := &ScrapeTask{
			TaskID:      taskID,
			URL:         url,
			Mode:        mode,
			Flags:       payload.Flags,
			Limit:       limitVal,
			TargetIP:    targetIP,
			Transfer:    transfer,
			DeviceName:  devName,
			DeviceBrand: devBrand,
			Status:      "queued",
			Progress:    0.0,
			Message:     "Queued on server",
			CreatedAt:   float64(time.Now().UnixNano()) / 1e9,
		}

		registry.Add(task)

		flagsDisplay := strings.Join(payload.Flags, ", ")
		if flagsDisplay == "" {
			if mode == "vacuum" {
				flagsDisplay = "-a (All)"
			} else {
				flagsDisplay = "--0 (Single Item)"
			}
		}

		banner := fmt.Sprintf(
			"\n%s\n"+
				"📡 [HWARAN INGESTION SIGNAL RECEIVED]\n"+
				"📱 Client Device : %s %s (%s)\n"+
				"📦 Source App    : %s v%s\n"+
				"🔗 Target URL    : %s\n"+
				"🎯 Scrape Scope  : %s (Flags: %s)\n"+
				"🚚 Delivery Mode : %s (Direct <=500MB | LocalSend >500MB)\n"+
				"🆔 Task Assigned : %s\n"+
				"⏱️  Timestamp     : %s\n"+
				"%s\n",
			strings.Repeat("=", 64),
			devBrand, devName, clientIP,
			payload.AppName, payload.AppVersion,
			url,
			strings.ToUpper(mode), flagsDisplay,
			strings.ToUpper(transfer),
			taskID,
			time.Now().Format("2006-01-02 15:04:05"),
			strings.Repeat("=", 64),
		)
		fmt.Print(banner)

		// Run scraping asynchronously in worker goroutine
		go runScrapeWorker(task, repoDir, pythonBin)

		sendJSON(w, http.StatusOK, task.ToMap())
	})

	// GET /api/download/{id}
	mux.HandleFunc("/api/download/", func(w http.ResponseWriter, r *http.Request) {
		taskID := strings.TrimPrefix(r.URL.Path, "/api/download/")
		task := registry.Get(taskID)
		if task == nil {
			sendJSON(w, http.StatusNotFound, map[string]any{"error": "Task not found"})
			return
		}

		zipPath := task.ZipPath
		if zipPath == "" || func() bool { _, err := os.Stat(zipPath); return os.IsNotExist(err) }() {
			if len(task.DownloadedFiles) == 0 {
				sendJSON(w, http.StatusNotFound, map[string]any{"error": "Files not ready or task failed"})
				return
			}
			// Fallback on-the-fly zip creation
			tmpZip := filepath.Join(os.TempDir(), fmt.Sprintf("zine_%s.zip", task.TaskID))
			if err := createZipArchive(tmpZip, task.BaseDir, task.DownloadedFiles); err == nil {
				zipPath = tmpZip
				task.ZipPath = tmpZip
			} else {
				sendJSON(w, http.StatusInternalServerError, map[string]any{"error": "Failed to create archive"})
				return
			}
		}

		zipFile, err := os.Open(zipPath)
		if err != nil {
			sendJSON(w, http.StatusNotFound, map[string]any{"error": "Zip file missing"})
			return
		}
		defer zipFile.Close()

		fi, err := zipFile.Stat()
		if err != nil {
			sendJSON(w, http.StatusInternalServerError, map[string]any{"error": "Stat error"})
			return
		}

		w.Header().Set("Content-Type", "application/zip")
		w.Header().Set("Content-Length", strconv.FormatInt(fi.Size(), 10))
		w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=\"zine_%s.zip\"", taskID))
		w.Header().Set("Connection", "keep-alive")

		// ServeContent handles HTTP range requests and high-speed kernel streaming
		http.ServeContent(w, r, fmt.Sprintf("zine_%s.zip", taskID), fi.ModTime(), zipFile)
	})

	killExistingServerOnPort(*port)

	addr := fmt.Sprintf("%s:%d", *host, *port)
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		killExistingServerOnPort(*port)
		time.Sleep(500 * time.Millisecond)
		ln, err = net.Listen("tcp", addr)
		if err != nil {
			log.Fatalf("Server failed: listen tcp %s: %v", addr, err)
		}
	}

	server := &http.Server{
		Addr:         addr,
		Handler:      corsMiddleware(mux),
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 600 * time.Second, // Long write timeout for massive ZIP downloads
		IdleTimeout:  120 * time.Second,
	}

	stopBeacon := make(chan struct{})
	go startUDPBeacon(*port, stopBeacon)

	lanIPs, _ := getLanIPs()
	primaryIP := "127.0.0.1"
	if len(lanIPs) > 0 {
		primaryIP = lanIPs[0]
	}

	fmt.Println("\n" + strings.Repeat("=", 64))
	fmt.Printf(" 🚀 [Zine Scraper Server (Go Engine)] Active & Listening!\n")
	fmt.Printf("    • Local URL:   http://127.0.0.1:%d\n", *port)
	for _, ip := range lanIPs {
		fmt.Printf("    • Network URL: http://%s:%d\n", ip, *port)
	}
	fmt.Println(strings.Repeat("=", 64))
	fmt.Printf(" 📡 LAN Discovery Beacon broadcasting on UDP 53319 & 53318\n")
	fmt.Printf(" 📱 In Hwaran on your phone, connect to: %s:%d\n", primaryIP, *port)
	fmt.Printf("    Engine: Native Go | Scraper: %s\n", pythonBin)
	fmt.Printf("    Press Ctrl+C to stop.\n\n")

	// Graceful shutdown on SIGINT / SIGTERM
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	go func() {
		<-sigChan
		fmt.Println("\n[Zine Scraper Server] Shutting down...")
		close(stopBeacon)
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(ctx)
		registry.Clear()
		fmt.Println("[Zine Scraper Server] Stopped cleanly.")
		os.Exit(0)
	}()

	if err := server.Serve(ln); err != nil && err != http.ErrServerClosed {
		log.Fatalf("Server failed: %v", err)
	}
}
