package main

import (
	"archive/zip"
	"bufio"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"io/fs"
	"log"
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

// createZipArchive creates a Deflate ZIP archive with an optional series root directory.
func createZipArchive(destZip string, baseDir string, files []string, seriesTitle string) error {
	out, err := os.Create(destZip)
	if err != nil {
		return err
	}
	defer out.Close()

	zw := zip.NewWriter(out)
	defer zw.Close()

	cleanSeries := strings.TrimSpace(seriesTitle)
	if cleanSeries != "" {
		re := regexp.MustCompile(`[^a-zA-Z0-9_\-\. ]+`)
		cleanSeries = strings.TrimSpace(re.ReplaceAllString(cleanSeries, "_"))
	}

	for _, file := range files {
		rel, err := filepath.Rel(baseDir, file)
		if err != nil {
			rel = filepath.Base(file)
		}

		slashRel := filepath.ToSlash(rel)
		if cleanSeries != "" && !strings.EqualFold(cleanSeries, "zine_scraper") {
			if !strings.HasPrefix(slashRel, cleanSeries+"/") && slashRel != cleanSeries {
				rel = filepath.Join(cleanSeries, rel)
			}
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
		for _, f := range task.Flags {
			if f == "-a" || f == "--all" {
				args = append(args, "--a")
			} else {
				args = append(args, f)
			}
		}
	} else if task.Mode == "quick_grab" {
		args = append(args, "--0")
	} else if task.Mode == "vacuum" {
		if task.Limit != nil && *task.Limit > 0 {
			args = append(args, fmt.Sprintf("--%d", *task.Limit))
		} else {
			args = append(args, "--a")
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
				title := strings.Trim(strings.TrimSpace(cleanLine[idx+len("◆ "):]), "◆ ")
				title = strings.TrimSpace(title)
				if title != "" && !strings.Contains(strings.ToLower(title), "zine scraper") && !strings.Contains(strings.ToLower(title), "batch mode") {
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

	if task.MediaTitle == "" && len(newFiles) > 0 {
		for _, f := range newFiles {
			rel, err := filepath.Rel(targetRoot, f)
			if err == nil {
				parts := strings.Split(filepath.ToSlash(rel), "/")
				if len(parts) > 1 && !strings.HasPrefix(parts[0], "Chapter") && !strings.HasPrefix(parts[0], "Episode") {
					task.MediaTitle = parts[0]
					break
				}
			}
		}
		if task.MediaTitle == "" && task.URL != "" {
			parts := strings.Split(strings.TrimRight(task.URL, "/"), "/")
			if len(parts) > 0 {
				last := parts[len(parts)-1]
				last = strings.ReplaceAll(last, "-", " ")
				last = strings.ReplaceAll(last, "_", " ")
				task.MediaTitle = strings.Title(last)
			}
		}
	}

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
	if err := createZipArchive(tmpZip, targetRoot, newFiles, task.MediaTitle); err == nil {
		task.ZipPath = tmpZip
	} else {
		log.Printf("Warning: Could not pre-package zip for task %s: %v", task.TaskID, err)
	}

	// Direct Stream: instant HTTP streaming directly to Hwaran
	task.Status = "completed"
	task.Progress = 1.0
	task.Message = fmt.Sprintf("Media ready for direct download (%.1f MB)", sizeMB)
	log.Printf("[TASK %s] Media ready for direct download: %s (%.1f MB)", task.TaskID, zipFileName, sizeMB)
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
				"🚚 Delivery Mode : DIRECT STREAM\n"+
				"🆔 Task Assigned : %s\n"+
				"⏱️  Timestamp     : %s\n"+
				"%s\n",
			strings.Repeat("=", 64),
			devBrand, devName, clientIP,
			payload.AppName, payload.AppVersion,
			url,
			strings.ToUpper(mode), flagsDisplay,
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
			if err := createZipArchive(tmpZip, task.BaseDir, task.DownloadedFiles, task.MediaTitle); err == nil {
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
