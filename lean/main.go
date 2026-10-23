// DataClaw 精简版：单二进制（Go + SQLite + 原生 Web）
//
// 设计取舍（相对 v1.0 参考实现 17.9k 行 Python + 13.1k 行 TS）：
//   - 服务端只提供 JSON API + 3 个 HTML 外壳，渲染交给 ~600 行原生 JS（无构建、无框架）
//   - 应用状态用「单表文档存储」(kind,id,json)，省掉 25 张表与 ORM 映射
//   - 只保留一条主干：员工 → 会话 → 工具（SQL 网关/产物）→ 审计，其余能力合并进管理页
//   - 分析数据仍走真实 SQLite + 真实 SQL（chatbi 场景），权限网关用词法分析实现
package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io/fs"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

//go:embed web
var webFS embed.FS

var (
	dataDir   = flag.String("data", "data", "数据目录（自动创建 app.db / demo.db）")
	addr      = flag.String("addr", "127.0.0.1:8788", "监听地址")
	secret    = []byte("dataclaw-lean-secret-change-me")
	app       = &App{}
	startedAt = time.Now()
)

func main() {
	flag.Parse()
	if err := app.Open(*dataDir); err != nil {
		log.Fatalf("open store: %v", err)
	}
	defer app.Close()
	if err := app.EnsureSeed(); err != nil {
		log.Fatalf("seed: %v", err)
	}

	web, _ := fs.Sub(webFS, "web")
	mux := http.NewServeMux()

	// 页面外壳
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/", "/app":
			if app.uid(r) == "" {
				http.Redirect(w, r, "/login", http.StatusFound)
				return
			}
			serveFile(w, r, web, "app.html")
		case "/admin":
			if !app.isAdmin(r) {
				http.Redirect(w, r, "/app", http.StatusFound)
				return
			}
			serveFile(w, r, web, "admin.html")
		case "/login":
			serveFile(w, r, web, "login.html")
		default:
			http.NotFound(w, r)
		}
	})
	mux.Handle("/static/", http.StripPrefix("/static/", http.FileServer(http.FS(web))))

	// API
	mux.HandleFunc("/api/health", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, 200, map[string]any{"status": "ok", "version": "1.1.0-lean", "uptime": int(time.Since(startedAt).Seconds())})
	})
	mux.HandleFunc("/api/login", app.handleLogin)
	mux.HandleFunc("/api/logout", app.handleLogout)
	mux.HandleFunc("/api/me", app.auth(app.handleMe))
	mux.HandleFunc("/api/bootstrap", app.auth(app.handleBootstrap))
	mux.HandleFunc("/api/employee", app.auth(app.handleCreateEmployee))
	mux.HandleFunc("/api/employee/update", app.auth(app.handleUpdateEmployee))
	mux.HandleFunc("/api/employee/skill", app.auth(app.handleEmployeeSkill))
	mux.HandleFunc("/api/sessions", app.auth(app.handleSessions))
	mux.HandleFunc("/api/chat", app.auth(app.handleChat))
	mux.HandleFunc("/api/chat/approve", app.auth(app.handleApprove))
	mux.HandleFunc("/api/artifact/", app.auth(app.handleArtifact))
	mux.HandleFunc("/api/admin", app.admin(app.handleAdmin))
	mux.HandleFunc("/api/policy", app.admin(app.handlePolicy))
	mux.HandleFunc("/api/guard/preview", app.admin(app.handleGuardPreview))
	mux.HandleFunc("/api/agent/assign", app.admin(app.handleAssign))
	mux.HandleFunc("/api/skill/install", app.auth(app.handleSkillInstall))
	mux.HandleFunc("/api/knowledge/search", app.auth(app.handleKnowledge))
	mux.HandleFunc("/api/channels/web/events", app.handleChannelInbound) // 免登录，校验 token

	log.Printf("DataClaw Lean -> http://%s", *addr)
	srv := &http.Server{Addr: *addr, Handler: logging(mux), ReadHeaderTimeout: 10 * time.Second}
	if err := srv.ListenAndServe(); err != nil {
		log.Fatal(err)
	}
}

func serveFile(w http.ResponseWriter, r *http.Request, fsys fs.FS, name string) {
	b, err := fs.ReadFile(fsys, name)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write(b)
}

func logging(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t := time.Now()
		next.ServeHTTP(w, r)
		if strings.HasPrefix(r.URL.Path, "/api/") {
			log.Printf("%-6s %-28s %4dms", r.Method, r.URL.Path, time.Since(t).Milliseconds())
		}
	})
}

// ---------------- 会话与鉴权（HMAC 签名 cookie，省掉 JWT 依赖） ----------------

func (a *App) setSession(w http.ResponseWriter, uid string) {
	exp := strconv.FormatInt(time.Now().Add(12*time.Hour).Unix(), 10)
	mac := hmac.New(sha256.New, secret)
	mac.Write([]byte(uid + "|" + exp))
	http.SetCookie(w, &http.Cookie{
		Name: "dc", Value: uid + "|" + exp + "|" + hex.EncodeToString(mac.Sum(nil)),
		Path: "/", HttpOnly: true, SameSite: http.SameSiteLaxMode, MaxAge: 12 * 3600,
	})
}

func (a *App) uid(r *http.Request) string {
	c, err := r.Cookie("dc")
	if err != nil {
		return ""
	}
	parts := strings.Split(c.Value, "|")
	if len(parts) != 3 {
		return ""
	}
	mac := hmac.New(sha256.New, secret)
	mac.Write([]byte(parts[0] + "|" + parts[1]))
	if hex.EncodeToString(mac.Sum(nil)) != parts[2] {
		return ""
	}
	exp, _ := strconv.ParseInt(parts[1], 10, 64)
	if exp < time.Now().Unix() {
		return ""
	}
	return parts[0]
}

func (a *App) auth(h func(http.ResponseWriter, *http.Request, string)) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		uid := a.uid(r)
		if uid == "" {
			writeJSON(w, 401, errBody("UNAUTHORIZED", "请先登录"))
			return
		}
		h(w, r, uid)
	}
}

func (a *App) admin(h func(http.ResponseWriter, *http.Request, string)) http.HandlerFunc {
	return a.auth(func(w http.ResponseWriter, r *http.Request, uid string) {
		u, _ := get[User](a.db, "user", uid)
		if u.Role != "platform_admin" {
			writeJSON(w, 403, errBody("FORBIDDEN", "需要管理员权限"))
			return
		}
		h(w, r, uid)
	})
}

func (a *App) isAdmin(r *http.Request) bool {
	uid := a.uid(r)
	if uid == "" {
		return false
	}
	u, _ := get[User](a.db, "user", uid)
	return u.Role == "platform_admin"
}

// ---------------- 响应工具 ----------------

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func errBody(code, msg string) map[string]any {
	return map[string]any{"error": map[string]string{"code": code, "message": msg}}
}

func now() string { return time.Now().Format(time.RFC3339) }

func newID(prefix string) string {
	return fmt.Sprintf("%s_%x", prefix, time.Now().UnixNano()%0xFFFFFFFFFFFF)
}

func (a *App) audit(actor, action, target, risk, result string, detail any) {
	_ = put(a.db, "audit", newID("au"), Audit{
		ID: newID("au"), Ts: now(), Actor: actor, Action: action,
		Target: target, Risk: risk, Result: result, Detail: detail,
	})
}

func (a *App) path(parts ...string) string {
	return filepath.Join(append([]string{a.dir}, parts...)...)
}

func fileExists(p string) bool { _, err := os.Stat(p); return err == nil }
