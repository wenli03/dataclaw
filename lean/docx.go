package main

import (
	"archive/zip"
	"fmt"
	"os"
	"strings"
)

// buildDocx 生成最小可用的 .docx，并用 OOXML 的 w:ins / w:del 写入修订痕迹。
// 只依赖标准库（archive/zip），不引入文档库。
func buildDocx(path, title string, risks []Risk) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	zw := zip.NewWriter(f)
	defer zw.Close()

	write := func(name, content string) error {
		w, err := zw.Create(name)
		if err != nil {
			return err
		}
		_, err = w.Write([]byte(content))
		return err
	}

	if err := write("[Content_Types].xml", `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>`); err != nil {
		return err
	}
	if err := write("_rels/.rels", `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>`); err != nil {
		return err
	}

	var b strings.Builder
	b.WriteString(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>`)
	b.WriteString(para(title, true))
	b.WriteString(para("说明：以下为 DataClaw 数字员工按《标准合同审查规则 V3》生成的初审建议。修订采用 Word 修订痕迹（删除线=原文，下划线=建议），最终结论须由法务复核。", false))
	date := "2026-10-23T00:00:00Z"
	for i, r := range risks {
		b.WriteString(para(fmt.Sprintf("%s %s（风险：%s）", r.Clause, r.Title, levelCN(r.Level)), true))
		b.WriteString(para("问题："+r.Issue, false))
		if r.Original != "" {
			b.WriteString(tracked(i, r.Original, "", date))
		}
		b.WriteString(tracked(i, "", r.Suggestion, date))
		b.WriteString(para("", false))
	}
	b.WriteString(`<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>`)
	b.WriteString(`</w:body></w:document>`)

	return write("word/document.xml", b.String())
}

func para(text string, bold bool) string {
	rpr := ""
	if bold {
		rpr = `<w:rPr><w:b/><w:sz w:val="28"/></w:rPr>`
	}
	return `<w:p><w:r>` + rpr + `<w:t xml:space="preserve">` + escXML(text) + `</w:t></w:r></w:p>`
}

// tracked 生成一条带修订痕迹的段落：原文用 w:del（删除线），建议用 w:ins（下划线）。
func tracked(seed int, del, ins, date string) string {
	var b strings.Builder
	b.WriteString(`<w:p>`)
	if del != "" {
		b.WriteString(fmt.Sprintf(`<w:del w:id="%d" w:author="DataClaw" w:date="%s"><w:r><w:rPr><w:strike/></w:rPr><w:delText xml:space="preserve">%s</w:delText></w:r></w:del>`, seed*2+1, date, escXML(del)))
	}
	if ins != "" {
		b.WriteString(fmt.Sprintf(`<w:ins w:id="%d" w:author="DataClaw" w:date="%s"><w:r><w:rPr><w:u w:val="single"/><w:color w:val="1F6FEB"/></w:rPr><w:t xml:space="preserve">%s</w:t></w:r></w:ins>`, seed*2+2, date, escXML(ins)))
	}
	b.WriteString(`</w:p>`)
	return b.String()
}

func levelCN(l string) string {
	switch l {
	case "high":
		return "高"
	case "medium":
		return "中"
	default:
		return "低"
	}
}

func escXML(s string) string {
	return strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;", `"`, "&quot;", "'", "&apos;").Replace(s)
}
