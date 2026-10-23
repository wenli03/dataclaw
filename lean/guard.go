package main

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// GuardResult 是数据网关的返回：改写前后 SQL、行、脱敏列、命中的规则、拒绝原因。
type GuardResult struct {
	OK       bool             `json:"ok"`
	Original string           `json:"original"`
	SQL      string           `json:"sql"`
	Rows     []map[string]any `json:"rows"`
	Columns  []string         `json:"columns"`
	Masked   []string         `json:"masked"`
	Rules    []GuardRule      `json:"rules"`
	Denied   string           `json:"denied,omitempty"`
	Ms       int64            `json:"ms"`
	RowCount int              `json:"rowCount"`
}

type GuardRule struct {
	Type   string `json:"type"`
	Detail string `json:"detail"`
}

var (
	reTable   = regexp.MustCompile(`(?i)\bfrom\s+([a-z_][a-z0-9_]*)|\bjoin\s+([a-z_][a-z0-9_]*)`)
	reForbid  = regexp.MustCompile(`(?i)\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|replace|truncate|grant|revoke)\b`)
	reWhere   = regexp.MustCompile(`(?i)\bwhere\b`)
	reTail    = regexp.MustCompile(`(?i)\b(group\s+by|order\s+by|having|limit)\b`)
	reLimit   = regexp.MustCompile(`(?i)\blimit\s+(\d+)`)
	allowedBT = map[string][]string{}
)

// guard 执行「表/列鉴权 → * 展开 → 行级过滤注入 → LIMIT 收敛 → 执行 → 脱敏」。
// 说明：精简版用词法分析而非完整 AST（v1.0 用 sqlglot）；对"只允许单条 SELECT"的场景等价，
// 生产建议换 sqlglot / JSqlParser / Calcite，见 docs/06。
func (a *App) guard(uid, role, q string, limit int) GuardResult {
	t0 := time.Now()
	res := GuardResult{Original: q, SQL: q}
	finish := func(r GuardResult) GuardResult { r.Ms = time.Since(t0).Milliseconds(); return r }

	q = strings.TrimSpace(strings.TrimSuffix(strings.TrimSpace(q), ";"))
	low := " " + strings.ToLower(q) + " "
	if q == "" {
		return finish(GuardResult{Denied: "SQL 为空"})
	}
	if strings.Contains(q, ";") {
		return finish(GuardResult{Denied: "仅支持单条语句"})
	}
	if !strings.HasPrefix(strings.ToLower(q), "select") && !strings.HasPrefix(strings.ToLower(q), "with") {
		return finish(GuardResult{Denied: "仅支持只读查询（SELECT）"})
	}
	if m := reForbid.FindString(low); m != "" {
		// 允许 with ... select，但出现写关键字即拒绝
		if !strings.Contains(low, " select ") {
			return finish(GuardResult{Denied: "检测到写操作：" + strings.TrimSpace(m)})
		}
		return finish(GuardResult{Denied: "检测到写操作：" + strings.TrimSpace(m)})
	}

	// 表级鉴权
	tables := []string{}
	for _, m := range reTable.FindAllStringSubmatch(q, -1) {
		name := m[1]
		if name == "" {
			name = m[2]
		}
		tables = append(tables, strings.ToLower(name))
	}
	if len(tables) == 0 {
		return finish(GuardResult{Denied: "无法解析查询的表"})
	}
	pols := a.policyFor(uid, role)
	rowFilters := []string{}
	for _, t := range tables {
		ok, filter, reason := resolveTable(pols, t)
		if !ok {
			return finish(GuardResult{Denied: reason})
		}
		if filter != "" {
			rowFilters = append(rowFilters, filter)
		}
		if _, ok := allowedBT[t]; !ok {
			allowedBT[t] = a.columnsOf(t)
		}
	}

	// 列鉴权 + SELECT * 展开
	maskOf := map[string]string{}
	deniedCols := map[string]bool{}
	for _, p := range pols {
		parts := strings.SplitN(p.Resource, ":", 2)
		if len(parts) != 2 || !strings.HasPrefix(parts[0], "column") {
			continue
		}
		ref := parts[1]
		col := ref
		if i := strings.LastIndex(ref, "."); i >= 0 {
			col = ref[i+1:]
		}
		if p.Action == "deny" {
			deniedCols[col] = true
		} else if p.Mask != "" && p.Mask != "none" {
			maskOf[col] = p.Mask
		}
	}
	rewritten := q
	if strings.Contains(strings.ToLower(q), "select *") {
		cols := []string{}
		for _, t := range tables {
			for _, c := range allowedBT[t] {
				if !deniedCols[c] {
					cols = append(cols, c)
				}
			}
			break // 演示查询均为单表
		}
		rewritten = regexp.MustCompile(`(?i)select\s+\*`).ReplaceAllString(q, "select "+strings.Join(cols, ", "))
		res.Rules = append(res.Rules, GuardRule{"column", fmt.Sprintf("SELECT * 展开为 %d 个已授权列", len(cols))})
	}
	for c := range deniedCols {
		if strings.Contains(strings.ToLower(rewritten), c) {
			return finish(GuardResult{Denied: "无权访问字段 " + c})
		}
	}

	// 行级过滤注入（简化：与现有 WHERE 以 AND 合并）
	if len(rowFilters) > 0 {
		cond := strings.Join(rowFilters, " AND ")
		if loc := reWhere.FindStringIndex(rewritten); loc != nil {
			rewritten = rewritten[:loc[1]] + " (" + cond + ") AND (" + strings.TrimSpace(rewritten[loc[1]:]) + ")"
		} else if loc := reTail.FindStringIndex(rewritten); loc != nil {
			rewritten = rewritten[:loc[0]] + " WHERE " + cond + " " + rewritten[loc[0]:]
		} else {
			rewritten += " WHERE " + cond
		}
		res.Rules = append(res.Rules, GuardRule{"row", "注入行级过滤：" + cond})
	}

	// LIMIT 收敛
	if limit <= 0 || limit > 500 {
		limit = 500
	}
	if m := reLimit.FindStringSubmatch(rewritten); m != nil {
		if n, _ := strconv.Atoi(m[1]); n > limit {
			rewritten = reLimit.ReplaceAllString(rewritten, fmt.Sprintf("LIMIT %d", limit))
			res.Rules = append(res.Rules, GuardRule{"limit", fmt.Sprintf("LIMIT 收敛为 %d", limit)})
		}
	} else {
		rewritten += fmt.Sprintf(" LIMIT %d", limit)
		res.Rules = append(res.Rules, GuardRule{"limit", fmt.Sprintf("附加 LIMIT %d", limit)})
	}
	res.SQL = rewritten

	// 执行（只读连接）
	rows, err := a.queryReadOnly(rewritten)
	if err != nil {
		res.Denied = "查询失败：" + err.Error()
		a.audit(uid, "sql_query", strings.Join(tables, ","), "medium", "error", map[string]any{"sql": rewritten, "error": err.Error()})
		return finish(res)
	}
	res.OK, res.Rows, res.RowCount = true, rows, len(rows)
	if len(rows) > 0 {
		for k := range rows[0] {
			res.Columns = append(res.Columns, k)
		}
	}
	for col, mode := range maskOf {
		hit := false
		for _, r := range rows {
			if v, ok := r[col]; ok {
				r[col] = applyMask(v, mode)
				hit = true
			}
		}
		if hit {
			res.Masked = append(res.Masked, col)
			res.Rules = append(res.Rules, GuardRule{"mask", fmt.Sprintf("%s 按 %s 脱敏", col, mode)})
		}
	}
	risk := "low"
	if len(res.Masked) > 0 {
		risk = "medium"
	}
	a.audit(uid, "sql_query", strings.Join(tables, ","), risk, "success", map[string]any{
		"sql": rewritten, "original": q, "rows": len(rows), "masked": res.Masked, "ms": res.Ms,
	})
	return finish(res)
}

func resolveTable(pols []Policy, table string) (bool, string, string) {
	// 用户级策略优先；无用户级才回退角色兜底（v1.0 踩过的 P0）
	userHit := false
	allow, filter, denyReason := false, "", ""
	scan := func(p Policy, isUser bool) bool {
		if !strings.EqualFold(p.Resource, "table:"+table) {
			return false
		}
		if isUser {
			userHit = true
		}
		if p.Action == "deny" {
			denyReason = fmt.Sprintf("无权访问表 %s（命中策略：%s %s）", table, p.Who, p.Note)
			return true
		}
		allow = true
		if p.RowFilter != "" {
			filter = p.RowFilter
		}
		return false
	}
	for _, p := range pols {
		if strings.HasPrefix(p.Who, "user:") && scan(p, true) {
			return false, "", denyReason
		}
	}
	if !userHit {
		for _, p := range pols {
			if strings.HasPrefix(p.Who, "role:") && scan(p, false) {
				return false, "", denyReason
			}
		}
	}
	if !allow && !userHit {
		return false, "", fmt.Sprintf("无权访问表 %s（未授权，默认拒绝）", table)
	}
	return true, filter, ""
}

func applyMask(v any, mode string) any {
	s := fmt.Sprint(v)
	switch mode {
	case "mask":
		return "****"
	case "hash":
		h := sha256.Sum256([]byte(s))
		return "sha256:" + hex.EncodeToString(h[:])[:12]
	case "truncate":
		if len(s) > 4 {
			return s[:4] + "…"
		}
		return "…"
	}
	return v
}

func (a *App) queryReadOnly(q string) ([]map[string]any, error) {
	ro, err := sql.Open("sqlite", "file:"+a.path("demo.db")+"?mode=ro")
	if err != nil {
		return nil, err
	}
	defer ro.Close()
	rows, err := ro.Query(q)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	cols, _ := rows.Columns()
	out := []map[string]any{}
	for rows.Next() {
		vals := make([]any, len(cols))
		ptrs := make([]any, len(cols))
		for i := range vals {
			ptrs[i] = &vals[i]
		}
		if err := rows.Scan(ptrs...); err != nil {
			return nil, err
		}
		m := map[string]any{}
		for i, c := range cols {
			if b, ok := vals[i].([]byte); ok {
				m[c] = string(b)
			} else {
				m[c] = vals[i]
			}
		}
		out = append(out, m)
	}
	return out, rows.Err()
}

func (a *App) columnsOf(table string) []string {
	rows, err := a.ana.Query("PRAGMA table_info(" + table + ")")
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var cid int
		var name, typ string
		var notnull, pk int
		var dflt any
		if rows.Scan(&cid, &name, &typ, &notnull, &dflt, &pk) == nil {
			out = append(out, name)
		}
	}
	return out
}

func (a *App) tables() []string { return []string{"worktime_fact", "crm_customer", "contract_clause"} }
