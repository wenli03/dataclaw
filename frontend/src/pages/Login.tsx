import React, { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Bot, ShieldCheck, Database, Zap, ArrowRight, KeyRound, User2 } from "lucide-react";
import { useAuth } from "../lib/auth";
import { Button, Input, toast } from "../components/ui";
import { cx } from "../lib/format";

const DEMO = [
  { u: "admin", p: "admin123", label: "平台管理员", desc: "张明 · 数智事业部" },
  { u: "analyst", p: "123456", label: "数据分析师", desc: "林知微 · 数据分析组" },
  { u: "sales", p: "123456", label: "销售经理", desc: "程景舟 · 销售部" },
  { u: "legal", p: "123456", label: "法务顾问", desc: "顾守正 · 法务部" },
];

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const loc = useLocation() as any;
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await login(username, password);
      toast("登录成功，欢迎回来");
      nav(loc.state?.from || "/chat", { replace: true });
    } catch (err: any) {
      toast(err?.message || "登录失败", "error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-full">
      {/* 品牌侧 */}
      <div className="relative hidden w-[52%] flex-col justify-between overflow-hidden bg-ink-900 p-10 text-white lg:flex">
        <div className="absolute inset-0 grid-bg opacity-40" />
        <div className="absolute -right-24 -top-24 h-80 w-80 rounded-full bg-brand-600/30 blur-3xl" />
        <div className="absolute -bottom-32 left-10 h-96 w-96 rounded-full bg-teal-500/20 blur-3xl" />

        <div className="relative">
          <div className="flex items-center gap-3">
            <div className="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-brand-400 to-brand-700 shadow-lg">
              <Bot size={22} />
            </div>
            <div>
              <div className="text-[18px] font-semibold tracking-tight">DataClaw</div>
              <div className="text-[11.5px] text-white/50">企业级数字员工平台 · 汉得灵舟</div>
            </div>
          </div>
        </div>

        <div className="relative max-w-[520px]">
          <h1 className="text-[34px] font-semibold leading-[1.25] tracking-tight">
            让企业零门槛拥有
            <br />
            无数个全天候在线的
            <span className="bg-gradient-to-r from-teal-300 to-brand-300 bg-clip-text text-transparent">「数字员工」</span>
          </h1>
          <p className="mt-4 text-[13.5px] leading-relaxed text-white/60">
            内置数据能力的智能体平台：一句话出大屏、一句话出拜访指南、一句话审完合同。
            私有化部署、容器沙箱、权限继承自你的账号，数据不出域。
          </p>
          <div className="mt-8 grid grid-cols-3 gap-3">
            {[
              { icon: ShieldCheck, t: "物理 + 权限双隔离", d: "每用户独占工作空间" },
              { icon: Database, t: "知识中台底座", d: "结构化 + 非结构化融合" },
              { icon: Zap, t: "对话即交付", d: "真实产物，非聊天" },
            ].map((f) => (
              <div key={f.t} className="rounded-xl border border-white/10 bg-white/5 p-3 backdrop-blur">
                <f.icon size={16} className="text-teal-300" />
                <div className="mt-2 text-[12px] font-medium">{f.t}</div>
                <div className="mt-0.5 text-[10.5px] leading-snug text-white/45">{f.d}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="relative flex items-center gap-4 text-[11px] text-white/35">
          <span>© 2026 上海汉得信息技术股份有限公司</span>
          <span className="h-3 w-px bg-white/15" />
          <span>股票代码 300170</span>
        </div>
      </div>

      {/* 表单侧 */}
      <div className="flex flex-1 items-center justify-center bg-surface-100 px-6 py-10">
        <div className="w-full max-w-[390px]">
          <div className="mb-7 lg:hidden">
            <div className="flex items-center gap-2.5">
              <div className="grid h-10 w-10 place-items-center rounded-xl bg-brand-600 text-white">
                <Bot size={20} />
              </div>
              <div>
                <div className="text-[16px] font-semibold">DataClaw</div>
                <div className="text-[11px] text-ink-400">企业级数字员工平台</div>
              </div>
            </div>
          </div>

          <h2 className="text-[22px] font-semibold tracking-tight text-ink-900">登录工作台</h2>
          <p className="mt-1 text-[12.5px] text-ink-500">使用企业账号登录，权限将自动继承到你的数字员工</p>

          <form onSubmit={submit} className="mt-6 space-y-3.5">
            <div>
              <label className="label">账号</label>
              <div className="relative">
                <User2 size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
                <Input className="pl-9" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="username" autoComplete="username" />
              </div>
            </div>
            <div>
              <label className="label">口令</label>
              <div className="relative">
                <KeyRound size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
                <Input
                  className="pl-9"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••"
                  autoComplete="current-password"
                />
              </div>
            </div>
            <Button type="submit" loading={loading} className="mt-1 w-full !py-2.5" icon={<ArrowRight size={15} />}>
              进入工作台
            </Button>
          </form>

          <div className="mt-7">
            <div className="mb-2 flex items-center gap-2 text-[11px] text-ink-400">
              <span className="h-px flex-1 bg-surface-300" />
              演示账号（点击填充）
              <span className="h-px flex-1 bg-surface-300" />
            </div>
            <div className="grid grid-cols-2 gap-2">
              {DEMO.map((d) => (
                <button
                  key={d.u}
                  type="button"
                  onClick={() => {
                    setUsername(d.u);
                    setPassword(d.p);
                  }}
                  className={cx(
                    "rounded-xl border bg-white px-2.5 py-2 text-left transition hover:border-brand-300 hover:shadow-sm",
                    username === d.u ? "border-brand-400 ring-2 ring-brand-500/10" : "border-surface-300"
                  )}
                >
                  <div className="text-[12px] font-medium text-ink-800">{d.label}</div>
                  <div className="text-[10.5px] text-ink-400">
                    {d.u} · {d.desc}
                  </div>
                </button>
              ))}
            </div>
          </div>

          <p className="mt-6 text-[10.5px] leading-relaxed text-ink-400">
            演示环境数据均为模拟数据。生产部署时对接企业 SSO/LDAP，数字员工权限严格继承绑定用户。
          </p>
        </div>
      </div>
    </div>
  );
}
