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
	SiteName        string   `json:"site_name,omitempty"`
	Category        string   `json:"category,omitempty"`
	LinkType        string   `json:"link_type,omitempty"`
	TargetRoot      string   `json:"target_root,omitempty"`
	Status          string   `json:"status"` // queued, scraping, transferring, packaging, completed, failed
	Progress        float64  `json:"progress"`
	Message         string   `json:"message"`
	FileCount       int      `json:"file_count"`
	MediaTitle      string   `json:"media_title"`
	KeepOnPC        bool     `json:"keep_on_pc"`
	IsStopping      bool     `json:"is_stopping"`
	Error           string   `json:"error"`
	CreatedAt       float64  `json:"created_at"`
	ZipPath         string   `json:"-"`
	DownloadedFiles []string `json:"-"`
	BaseDir         string   `json:"-"`
	StagingDir      string   `json:"-"`
	cmd             *exec.Cmd `json:"-"`
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
		"keep_on_pc":   t.KeepOnPC,
		"is_stopping":  t.IsStopping,
		"device_name":  t.DeviceName,
		"device_brand": t.DeviceBrand,
		"site_name":    t.SiteName,
		"category":     t.Category,
		"link_type":    t.LinkType,
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
		fi, err := os.Stat(file)
		if err != nil || fi.IsDir() {
			continue
		}

		var entryName string
		slashFile := filepath.ToSlash(file)

		if cleanSeries != "" && !strings.EqualFold(cleanSeries, "zine_scraper") {
			parts := strings.Split(slashFile, "/")
			foundIdx := -1
			for i, p := range parts {
				if strings.EqualFold(p, cleanSeries) || (seriesTitle != "" && strings.EqualFold(p, seriesTitle)) {
					foundIdx = i
					break
				}
			}
			if foundIdx != -1 {
				entryName = strings.Join(parts[foundIdx:], "/")
			} else {
				rel, err := filepath.Rel(baseDir, file)
				if err != nil {
					rel = filepath.Base(file)
				}
				entryName = filepath.ToSlash(filepath.Join(cleanSeries, rel))
			}
		} else {
			rel, err := filepath.Rel(baseDir, file)
			if err != nil {
				rel = filepath.Base(file)
			}
			entryName = filepath.ToSlash(rel)
		}

		header, err := zip.FileInfoHeader(fi)
		if err != nil {
			continue
		}
		header.Name = entryName
		header.Method = zip.Deflate

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



type ResolvedLink struct {
	Valid      bool     `json:"valid"`
	URL        string   `json:"url"`
	SiteFolder string   `json:"site_folder"`
	SiteName   string   `json:"site_name"`
	Category   string   `json:"category"`
	LinkType   string   `json:"link_type"`
	IsChapter  bool     `json:"is_chapter"`
	Mode       string   `json:"mode"`
	Flags      []string `json:"flags"`
	TargetRoot string   `json:"target_root"`
	Title      string   `json:"title"`
	Error      string   `json:"error"`
}

// resolveLink queries Zine's core link_resolver to validate domains and resolve link architecture.
func resolveLink(repoDir string, pythonBin string, rawURL string, flags []string, mode string, limit *int) (*ResolvedLink, error) {
	orchestratorPath := filepath.Join(repoDir, "orchestrator.py")
	cmdArgs := []string{orchestratorPath, "--resolve-link", rawURL}
	for _, f := range flags {
		cmdArgs = append(cmdArgs, f)
	}
	if mode != "" && mode != "auto" {
		cmdArgs = append(cmdArgs, fmt.Sprintf("--mode=%s", mode))
	}
	if limit != nil && *limit > 0 {
		cmdArgs = append(cmdArgs, fmt.Sprintf("--%d", *limit))
	}

	cmd := exec.Command(pythonBin, cmdArgs...)
	cmd.Dir = repoDir
	out, err := cmd.Output()
	if err != nil && len(out) == 0 {
		return nil, fmt.Errorf("link resolver execution error: %v", err)
	}

	var res ResolvedLink
	if err := json.Unmarshal(out, &res); err != nil {
		return nil, fmt.Errorf("link resolution parsing failed: %v", err)
	}
	return &res, nil
}

// runScrapeWorker executes the zine scraper in the background with live console streaming and milestone telemetry.
func runScrapeWorker(task *ScrapeTask, repoDir string, pythonBin string) {
	task.Status = "scraping"
	task.Progress = 0.15
	task.Message = fmt.Sprintf("Starting engine for %s (%s)...", task.SiteName, task.Mode)

	targetRoot := task.TargetRoot
	if targetRoot == "" {
		home, _ := os.UserHomeDir()
		downloadsRoot := filepath.Join(home, "Downloads", "Zine")
		targetRoot = filepath.Join(downloadsRoot, "Quick grab")
		if task.Mode == "vacuum" {
			targetRoot = filepath.Join(downloadsRoot, "Vacuum")
		}
	}
	_ = os.MkdirAll(targetRoot, 0755)

	filesBefore := snapshotDirFiles(targetRoot)
	startTime := time.Now()

	// Assemble unbuffered CLI args for orchestrator.py
	orchestratorPath := filepath.Join(repoDir, "orchestrator.py")
	args := []string{"-u", orchestratorPath}
	args = append(args, task.Flags...)
	args = append(args, task.URL)

	log.Printf("[TASK %s] Spawning scraper: %s %s", task.TaskID, pythonBin, strings.Join(args, " "))
	cmd := exec.Command(pythonBin, args...)
	cmd.Dir = repoDir
	cmd.Env = append(os.Environ(),
		"PYTHONUNBUFFERED=1",
		fmt.Sprintf("ZINE_TASK_ID=%s", task.TaskID),
	)
	task.cmd = cmd

	stdoutPipe, err := cmd.StdoutPipe()
	if err != nil {
		task.Status = "failed"
		task.Error = fmt.Sprintf("Stdout pipe creation error: %v", err)
		task.Message = "Internal runner error"
		log.Printf("[TASK %s] [FAILED] %s", task.TaskID, task.Error)
		return
	}
	stderrPipe, err := cmd.StderrPipe()
	if err != nil {
		task.Status = "failed"
		task.Error = fmt.Sprintf("Stderr pipe creation error: %v", err)
		task.Message = "Internal runner error"
		log.Printf("[TASK %s] [FAILED] %s", task.TaskID, task.Error)
		return
	}

	if err := cmd.Start(); err != nil {
		task.Status = "failed"
		task.Error = fmt.Sprintf("Failed to launch scraper engine: %v", err)
		task.Message = "Scraper engine launch failed"
		log.Printf("[TASK %s] [FAILED] %s", task.TaskID, task.Error)
		return
	}

	ansiRegex := regexp.MustCompile(`\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])`)
	richRegex := regexp.MustCompile(`\[/?(?:[a-zA-Z0-9_#= -]+)\]`)
	pctRegex := regexp.MustCompile(`(\d+(?:\.\d+)?)%`)
	fractionRegex := regexp.MustCompile(`(\d+)\s*/\s*(\d+)`)

	linesChan := make(chan string, 128)
	var streamWg sync.WaitGroup

	scanStream := func(r io.Reader) {
		defer streamWg.Done()
		sc := bufio.NewScanner(r)
		b := make([]byte, 64*1024)
		sc.Buffer(b, 1024*1024)
		for sc.Scan() {
			linesChan <- sc.Text()
		}
	}

	streamWg.Add(2)
	go scanStream(stdoutPipe)
	go scanStream(stderrPipe)

	go func() {
		streamWg.Wait()
		close(linesChan)
	}()

	// Live console streaming & milestone parsing loop
	go func() {
		for rawText := range linesChan {
			clean := ansiRegex.ReplaceAllString(rawText, "")
			clean = richRegex.ReplaceAllString(clean, "")
			clean = strings.TrimSpace(clean)
			if clean == "" {
				continue
			}

			// Clean timestamped log directly to server console
			nowStr := time.Now().Format("15:04:05")
			fmt.Printf("[%s] [%s] %s\n", nowStr, task.TaskID, clean)

			cleanLower := strings.ToLower(clean)

			// 1. Title discovery
			if strings.Contains(clean, "◆ ") {
				idx := strings.Index(clean, "◆ ")
				title := strings.Trim(strings.TrimSpace(clean[idx+len("◆ "):]), "◆ ")
				title = strings.TrimSpace(title)
				if title != "" && !strings.Contains(strings.ToLower(title), "zine scraper") && !strings.Contains(strings.ToLower(title), "batch mode") {
					task.MediaTitle = title
				}
			}

			// 2. Error detection
			if strings.Contains(cleanLower, "failed") || strings.Contains(cleanLower, "error") || strings.Contains(cleanLower, "traceback") || strings.Contains(cleanLower, "unsupported") {
				task.Error = clean
				task.Message = clean
			}

			// 3. Stop / Revolt / Truncate detection
			if strings.Contains(clean, "Revolt") || strings.Contains(clean, "Ctrl+T") || strings.Contains(clean, "Stop limit reached") {
				task.IsStopping = true
				task.Message = clean
			}

			// 4. Progress percentage detection (e.g. yt-dlp "45.2% of 100MiB")
			if m := pctRegex.FindStringSubmatch(clean); len(m) > 1 {
				if pct, err := strconv.ParseFloat(m[1], 64); err == nil && pct > 0 {
					calcProg := 0.15 + (pct/100.0)*0.60
					if calcProg > task.Progress {
						task.Progress = calcProg
					}
					task.Message = clean
				}
			} else if m := fractionRegex.FindStringSubmatch(clean); len(m) > 2 {
				// e.g. "Chapter 1: 15/20 pages" or "Done: 5/10"
				curr, e1 := strconv.Atoi(m[1])
				total, e2 := strconv.Atoi(m[2])
				if e1 == nil && e2 == nil && total > 0 && curr <= total {
					calcProg := 0.15 + (float64(curr)/float64(total))*0.60
					if calcProg > task.Progress {
						task.Progress = calcProg
					}
					task.Message = clean
				}
			} else if strings.Contains(clean, "● Chapter") || strings.Contains(clean, "● Episode") || strings.Contains(clean, "Chapter ") {
				task.Message = clean
				if task.Progress < 0.70 {
					task.Progress += 0.03
				}
			} else if strings.Contains(clean, "✦ Done") || strings.Contains(clean, "Done:") {
				task.Message = clean
				task.Progress = 0.75
			}
		}
	}()

	cmdErr := cmd.Wait()
	_ = os.Remove(fmt.Sprintf("/tmp/zine_stop_%s", task.TaskID))
	if cmd.Process != nil {
		_ = os.Remove(fmt.Sprintf("/tmp/zine_stop_%d", cmd.Process.Pid))
	}

	// Detect new files created during scrape
	filesAfter := snapshotDirFiles(targetRoot)
	var newFiles []string

	for path, modTime := range filesAfter {
		if _, existed := filesBefore[path]; !existed || modTime.After(startTime.Add(-5*time.Second)) {
			newFiles = append(newFiles, path)
		}
	}

	sessionStatus := ""
	// Secondary fallback: inspect latest_session.json for recorded destination
	sessionFile := filepath.Join(repoDir, "Logs", "Downlode 💩", "latest_session.json")
	if sessionData, err := os.ReadFile(sessionFile); err == nil {
		var sess struct {
			Downloads []struct {
				Destination string `json:"destination"`
				Title       string `json:"title"`
				Status      string `json:"status"`
				Error       string `json:"error"`
			} `json:"downloads"`
		}
		if err := json.Unmarshal(sessionData, &sess); err == nil && len(sess.Downloads) > 0 {
			dl := sess.Downloads[0]
			sessionStatus = dl.Status
			if len(newFiles) == 0 && dl.Destination != "" {
				_ = filepath.WalkDir(dl.Destination, func(path string, d fs.DirEntry, err error) error {
					if err == nil && !d.IsDir() {
						newFiles = append(newFiles, path)
					}
					return nil
				})
				if len(newFiles) > 0 {
					targetRoot = dl.Destination
				}
			}
			if dl.Title != "" && task.MediaTitle == "" {
				task.MediaTitle = dl.Title
			}
			if dl.Error != "" && task.Error == "" {
				task.Error = dl.Error
			}
		}
	}

	// 10-minute fallback in targetRoot
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

	var totalBytes int64
	hasRealMedia := false
	for _, f := range newFiles {
		if fi, err := os.Stat(f); err == nil {
			totalBytes += fi.Size()
			lower := strings.ToLower(filepath.Base(f))
			isMediaExt := strings.HasSuffix(lower, ".mp4") || strings.HasSuffix(lower, ".mkv") || strings.HasSuffix(lower, ".webm") ||
				strings.HasSuffix(lower, ".mp3") || strings.HasSuffix(lower, ".flac") || strings.HasSuffix(lower, ".m4a") ||
				strings.HasSuffix(lower, ".opus") || strings.HasSuffix(lower, ".cbz") || strings.HasSuffix(lower, ".cbr") ||
				strings.HasSuffix(lower, ".epub") || strings.HasSuffix(lower, ".pdf") || strings.HasSuffix(lower, ".zip") ||
				strings.HasSuffix(lower, ".jpg") || strings.HasSuffix(lower, ".jpeg") || strings.HasSuffix(lower, ".png") ||
				strings.HasSuffix(lower, ".webp")

			isAvatarOrThumb := strings.Contains(lower, "avatar") || strings.Contains(lower, "thumbnail") || lower == "cover.jpg" || lower == "cover.png"
			if isMediaExt && (!isAvatarOrThumb || fi.Size() > 500*1024) && fi.Size() > 1024 {
				hasRealMedia = true
			}
		}
	}
	sizeMB := float64(totalBytes) / (1024 * 1024)

	// Check if scrape actually failed
	if len(newFiles) == 0 || !hasRealMedia || (sessionStatus == "failed" && sizeMB < 0.5) || (task.Error != "" && !hasRealMedia) {
		task.Status = "failed"
		if task.Error == "" {
			if cmdErr != nil {
				task.Error = fmt.Sprintf("Scraper process exited with error: %v", cmdErr)
			} else {
				task.Error = "No chapters or media files were saved from this URL."
			}
		}
		task.Message = task.Error
		if !task.KeepOnPC && task.StagingDir != "" {
			_ = os.RemoveAll(task.StagingDir)
		}
		log.Printf("[TASK %s] [FAILED] %s", task.TaskID, task.Error)
		return
	}

	// If title still empty, resolve from files or URL slug
	if task.MediaTitle == "" {
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

	// Packaging state
	task.Status = "packaging"
	task.Progress = 0.85
	task.Message = fmt.Sprintf("Packaging %d file(s) (%.1f MB)...", len(newFiles), sizeMB)
	log.Printf("[TASK %s] [PACKAGING] Compressing %d file(s) (%.1f MB)...", task.TaskID, len(newFiles), sizeMB)

	zipFileName := fmt.Sprintf("zine_%s.zip", task.TaskID)
	if task.MediaTitle != "" {
		re := regexp.MustCompile(`[^a-zA-Z0-9_\-\. ]+`)
		cleanTitle := re.ReplaceAllString(task.MediaTitle, "_")
		cleanTitle = strings.TrimSpace(cleanTitle)
		if cleanTitle != "" {
			zipFileName = fmt.Sprintf("%s.zip", cleanTitle)
		}
	}
	transitDir := filepath.Join(os.TempDir(), "zine_transfer")
	_ = os.MkdirAll(transitDir, 0755)
	tmpZip := filepath.Join(transitDir, zipFileName)
	if err := createZipArchive(tmpZip, targetRoot, newFiles, task.MediaTitle); err == nil {
		task.ZipPath = tmpZip
	} else {
		log.Printf("[TASK %s] Warning: Could not pre-package zip: %v", task.TaskID, err)
	}

	// Direct Stream: ready for download
	task.Status = "completed"
	task.Progress = 1.0
	task.Message = fmt.Sprintf("Media ready for direct download (%.1f MB)", sizeMB)
	log.Printf("[TASK %s] [COMPLETED] Media ready for direct download: %s (%.1f MB)", task.TaskID, zipFileName, sizeMB)
}

// killExistingServerOnPort terminates any older instance of zine-server or processes holding the port.
func killExistingServerOnPort(port int) {
	currentPID := os.Getpid()
	out, err := exec.Command("pgrep", "-x", "zine-server").Output()
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
	_ = exec.Command("fuser", "-k", "-TERM", fmt.Sprintf("%d/tcp", port)).Run()

	// Poll up to 1 second for port to be released
	portFree := false
	for i := 0; i < 10; i++ {
		time.Sleep(100 * time.Millisecond)
		conn, dialErr := net.DialTimeout("tcp", fmt.Sprintf("127.0.0.1:%d", port), 50*time.Millisecond)
		if dialErr != nil {
			portFree = true
			break
		}
		_ = conn.Close()
	}

	// If still occupied, escalate forcefully to SIGKILL
	if !portFree {
		out, err := exec.Command("pgrep", "-x", "zine-server").Output()
		if err == nil {
			pids := strings.Fields(strings.TrimSpace(string(out)))
			for _, pStr := range pids {
				pid, err := strconv.Atoi(pStr)
				if err == nil && pid != currentPID {
					proc, err := os.FindProcess(pid)
					if err == nil {
						_ = proc.Signal(syscall.SIGKILL)
					}
				}
			}
		}
		_ = exec.Command("fuser", "-k", "-KILL", fmt.Sprintf("%d/tcp", port)).Run()
		time.Sleep(250 * time.Millisecond)
	}
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

	// GET /api/tasks/{id}, DELETE /api/tasks/{id}, and POST /api/tasks/{id}/stop
	mux.HandleFunc("/api/tasks/", func(w http.ResponseWriter, r *http.Request) {
		trimmed := strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/tasks/"), "/")
		if trimmed == "" || trimmed == "clear" {
			return
		}
		parts := strings.Split(trimmed, "/")
		taskID := parts[0]
		subAction := ""
		if len(parts) > 1 {
			subAction = strings.ToLower(parts[1])
		}

		switch r.Method {
		case http.MethodGet:
			task := registry.Get(taskID)
			if task != nil {
				sendJSON(w, http.StatusOK, task.ToMap())
			} else {
				sendJSON(w, http.StatusNotFound, map[string]any{"error": "Task not found"})
			}
		case http.MethodPost:
			if subAction == "cancel" || subAction == "kill" {
				task := registry.Get(taskID)
				if task == nil {
					sendJSON(w, http.StatusNotFound, map[string]any{"error": "Task not found", "task_id": taskID})
					return
				}
				if task.cmd != nil && task.cmd.Process != nil {
					pid := task.cmd.Process.Pid
					_ = exec.Command("pkill", "-9", "-P", strconv.Itoa(pid)).Run()
					_ = task.cmd.Process.Kill()
					log.Printf("[TASK %s] [CANCELED] Process PID %d and child processes killed immediately", task.TaskID, pid)
				}
				task.Status = "canceled"
				task.Message = "Task canceled immediately by user."
				task.Error = "Canceled by user"
				_ = os.Remove(fmt.Sprintf("/tmp/zine_stop_%s", task.TaskID))
				sendJSON(w, http.StatusOK, map[string]any{
					"status":  "canceled",
					"message": "Task canceled immediately",
					"task_id": taskID,
				})
				return
			}

			if subAction == "stop" || subAction == "revolt" || subAction == "truncate" {
				task := registry.Get(taskID)
				if task == nil {
					sendJSON(w, http.StatusNotFound, map[string]any{"error": "Task not found", "task_id": taskID})
					return
				}
				if task.Status != "scraping" && task.Status != "queued" {
					sendJSON(w, http.StatusOK, map[string]any{
						"status":  task.Status,
						"message": fmt.Sprintf("Task is already in %s state", task.Status),
						"task_id": taskID,
					})
					return
				}

				task.IsStopping = true
				task.Message = "Stop signal sent (Ctrl+T). Finishing current media and wrapping up..."

				// Dispatch stop trigger file & SIGUSR1 to active process
				_ = os.WriteFile(fmt.Sprintf("/tmp/zine_stop_%s", task.TaskID), []byte("1"), 0644)
				if task.cmd != nil && task.cmd.Process != nil {
					pid := task.cmd.Process.Pid
					_ = os.WriteFile(fmt.Sprintf("/tmp/zine_stop_%d", pid), []byte("1"), 0644)
					_ = task.cmd.Process.Signal(syscall.SIGUSR1)
					log.Printf("[TASK %s] [STOP SIGNAL] Dispatched Revolt / Ctrl+T stop signal to PID %d", task.TaskID, pid)
				} else {
					log.Printf("[TASK %s] [STOP SIGNAL] Dispatched stop trigger file for task", task.TaskID)
				}

				sendJSON(w, http.StatusOK, map[string]any{
					"status":  "stopping",
					"action":  "truncate",
					"message": "Stop signal sent (Ctrl+T). Scraper will wrap up after current media.",
					"task_id": taskID,
				})
				return
			}
			http.Error(w, "Endpoint Not Found", http.StatusNotFound)
		case http.MethodDelete:
			task := registry.Get(taskID)
			if task != nil {
				if task.cmd != nil && task.cmd.Process != nil {
					pid := task.cmd.Process.Pid
					_ = exec.Command("pkill", "-9", "-P", strconv.Itoa(pid)).Run()
					_ = task.cmd.Process.Kill()
				}
				if task.ZipPath != "" {
					_ = os.Remove(task.ZipPath)
				}
				if task.StagingDir != "" {
					_ = os.RemoveAll(task.StagingDir)
				}
				_ = os.Remove(fmt.Sprintf("/tmp/zine_stop_%s", taskID))
				log.Printf("[TASK %s] [CLEANUP] Deleted task and purged all associated transit files", taskID)
			}
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
			KeepOnPC    bool     `json:"keep_on_pc"`
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

		mode := strings.ToLower(strings.TrimSpace(payload.Mode))
		if mode == "" || mode == "auto" {
			mode = "auto"
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

		// Resolve Link Architecture & Validate against Zine Scraper Engines
		resolved, err := resolveLink(repoDir, pythonBin, url, payload.Flags, mode, limitVal)
		if err != nil || (resolved != nil && !resolved.Valid) {
			errMsg := "Unsupported or invalid media URL"
			if resolved != nil && resolved.Error != "" {
				errMsg = resolved.Error
			} else if err != nil {
				errMsg = err.Error()
			}
			log.Printf("[REJECTED] Signal from %s (%s) rejected: URL=%s -> %s", devBrand, clientIP, url, errMsg)
			sendJSON(w, http.StatusBadRequest, map[string]any{
				"error": errMsg,
				"url":   url,
			})
			return
		}

		taskID := generateTaskID()
		task := &ScrapeTask{
			TaskID:      taskID,
			URL:         resolved.URL,
			Mode:        resolved.Mode,
			Flags:       resolved.Flags,
			Limit:       limitVal,
			TargetIP:    targetIP,
			Transfer:    transfer,
			DeviceName:  devName,
			DeviceBrand: devBrand,
			KeepOnPC:    payload.KeepOnPC,
			SiteName:    resolved.SiteName,
			Category:    resolved.Category,
			LinkType:    resolved.LinkType,
			TargetRoot:  resolved.TargetRoot,
			Status:      "queued",
			Progress:    0.0,
			Message:     "Queued on server",
			MediaTitle:  resolved.Title,
			CreatedAt:   float64(time.Now().UnixNano()) / 1e9,
		}

		registry.Add(task)

		flagsDisplay := strings.Join(resolved.Flags, ", ")
		if flagsDisplay == "" {
			if resolved.Mode == "vacuum" {
				flagsDisplay = "--a (All)"
			} else {
				flagsDisplay = "--0 (Single Item)"
			}
		}

		targetDisplay := resolved.TargetRoot
		keepDisplay := "YES (Saved to PC Zine Library)"

		banner := fmt.Sprintf(
			"\n%s\n"+
				"📡 [HWARAN INGESTION SIGNAL RECEIVED]\n"+
				"📱 Client Device : %s %s (%s)\n"+
				"📦 Source App    : %s v%s\n"+
				"🔗 Target URL    : %s\n"+
				"🏢 Site Engine   : %s (%s) [%s]\n"+
				"🎯 Scrape Scope  : %s (Flags: %s)\n"+
				"📁 Target Root   : %s\n"+
				"🚚 Delivery Mode : DIRECT STREAM\n"+
				"💾 Keep on PC    : %s\n"+
				"🆔 Task Assigned : %s\n"+
				"⏱️  Timestamp     : %s\n"+
				"%s\n",
			strings.Repeat("=", 64),
			devBrand, devName, clientIP,
			payload.AppName, payload.AppVersion,
			resolved.URL,
			resolved.SiteName, resolved.Category, strings.ToUpper(resolved.LinkType),
			strings.ToUpper(resolved.Mode), flagsDisplay,
			targetDisplay,
			keepDisplay,
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

		// Ephemeral post-delivery cleanup:
		// If KeepOnPC is false, schedule removal of the transit zip and staging dir after a short delay
		if !task.KeepOnPC {
			go func(t *ScrapeTask) {
				time.Sleep(30 * time.Second)
				if t.ZipPath != "" {
					_ = os.Remove(t.ZipPath)
					t.ZipPath = ""
				}
				if t.StagingDir != "" {
					_ = os.RemoveAll(t.StagingDir)
					t.StagingDir = ""
				}
				log.Printf("[TASK %s] [CLEANUP] Ephemeral transit files purged after successful delivery", t.TaskID)
			}(task)
		}
	})

	killExistingServerOnPort(*port)

	addr := fmt.Sprintf("%s:%d", *host, *port)
	lc := net.ListenConfig{
		Control: func(network, address string, c syscall.RawConn) error {
			var opErr error
			err := c.Control(func(fd uintptr) {
				opErr = syscall.SetsockoptInt(int(fd), syscall.SOL_SOCKET, syscall.SO_REUSEADDR, 1)
			})
			if err != nil {
				return err
			}
			return opErr
		},
	}
	ln, err := lc.Listen(context.Background(), "tcp", addr)
	if err != nil {
		killExistingServerOnPort(*port)
		time.Sleep(500 * time.Millisecond)
		ln, err = lc.Listen(context.Background(), "tcp", addr)
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
