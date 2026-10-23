import React, { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Activity, BookOpen, Bot, CheckSquare, ChevronDown, Database, FolderClosed, LayoutDashboard,
  LogOut, MessageSquare, Radio, Settings2, ShieldCheck, Sparkles, Store, Users, X, Menu,
} from "lucide-react";
import { cx } from "../../lib/format";
import { useAuth } from "../../lib/auth";
import { Avatar, Badge } from "../ui";

const workspaceNav = [
  { to: "/chat", label: "会话", icon: MessageSquare },
  { to: "/employees", label: "员工", icon: Bot },
  { to: "/skills", label: "技能超市", icon: Store },
  { to: "/tasks", label: "任务", icon: CheckSquare },
  { to: "/files", label: "文件", icon: FolderClosed },
];

const adminNav = [
  { to: "/admin", label: "运营总览", icon: LayoutDashboard, exact: true },
  { to: "/admin/users", label: "用户与角色", icon: Users },
  { to: "/admin/agents", label: "公共员工", icon: Bot },
  { to: "/admin/data", label: "数据安全", icon: ShieldCheck },
  { to: "/admin/knowledge", label: "知识中台", icon: BookOpen },
  { to: "/admin/channels", label: "渠道接入", icon: Radio },
  { to: "/admin/audit", label: "审计日志", icon: Activity },
];

function NavItem({ to, label, icon: Icon, exact }: { to: string; label: string; icon: any; exact?: boolean }) {
  return (
    <NavLink
      to={to}
      end={exact}
      className={({ isActive }) =>
        cx(
          "group flex items-center gap-2.5 rounded-xl px-3 py-2 text-[13px] transition-all",
          isActive ? "bg-brand-50 font-medium text-brand-700" : "text-ink-600 hover:bg-surface-100 hover:text-ink-900"
        )
      }
    >
      {({ isActive }) => (
        <>
          <Icon size={16} className={cx("shrink-0", isActive ? "text-brand-600" : "text-ink-400 group-hover:text-ink-600")} />
          <span>{label}</span>
        </>
      )}
    </NavLink>
  );
}

export default function AppShell() {
  const { user, isAdmin, logout } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [userMenu, setUserMenu] = useState(false);

  const isAdminSection = loc.pathname.startsWith("/admin");

  const sidebar = (
    <div className="flex h-full w-[232px] shrink-0 flex-col border-r border-surface-300/70 bg-white">
      <div className="flex items-center gap-2.5 px-4 pb-4 pt-5">
        <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 shadow-sm">
          <Bot size={19} className="text-white" />
        </div>
        <div className="min-w-0">
          <div className="text-[15px] font-semibold leading-tight tracking-tight text-ink-900">DataClaw</div>
          <div className="truncate text-[10.5px] text-ink-400">企业级数字员工平台</div>
        </div>
        <button className="ml-auto rounded-lg p-1 text-ink-400 lg:hidden" onClick={() => setMobileOpen(false)}>
          <X size={16} />
        </button>
      </div>

      <div className="px-3 pb-2">
        <div className="rounded-xl border border-surface-200 bg-gradient-to-br from-surface-50 to-brand-50/40 px-3 py-2.5">
          <div className="flex items-center gap-1.5 text-[11px] font-medium text-brand-700">
            <Sparkles size={12} /> 2026 数智事业部
          </div>
          <div className="mt-1 text-[11px] leading-snug text-ink-500">私有化部署 · 容器沙箱 · 数据不出域</div>
        </div>
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 pb-3">
        {workspaceNav.map((n) => (
          <NavItem key={n.to} {...n} />
        ))}

        {isAdmin && (
          <>
            <div className="mb-1 mt-4 flex items-center gap-1.5 px-3 text-[10.5px] font-medium uppercase tracking-wider text-ink-400">
              <Settings2 size={11} /> 管理后台
            </div>
            {adminNav.map((n) => (
              <NavItem key={n.to} {...n} />
            ))}
          </>
        )}

        {!isAdmin && (
          <div className="mt-4 rounded-xl border border-dashed border-surface-300 px-3 py-3">
            <div className="flex items-center gap-1.5 text-[11px] font-medium text-ink-600">
              <ShieldCheck size={12} /> 权限继承自你的账号
            </div>
            <div className="mt-1 text-[10.5px] leading-snug text-ink-400">
              数字员工只能访问你有权限的数据，越权操作会被拦截并审计。
            </div>
          </div>
        )}
      </nav>

      <div className="relative border-t border-surface-200 p-3">
        <button
          onClick={() => setUserMenu((v) => !v)}
          className="flex w-full items-center gap-2.5 rounded-xl px-2 py-2 text-left hover:bg-surface-100"
        >
          <Avatar name={user?.name} seed={user?.avatar || user?.username} size={32} />
          <div className="min-w-0 flex-1">
            <div className="truncate text-[12.5px] font-medium text-ink-900">{user?.name}</div>
            <div className="truncate text-[10.5px] text-ink-400">
              {user?.dept || "—"} · {user?.role === "platform_admin" ? "平台管理员" : user?.role === "dept_admin" ? "部门管理员" : "业务用户"}
            </div>
          </div>
          <ChevronDown size={14} className={cx("text-ink-400 transition", userMenu && "rotate-180")} />
        </button>
        {userMenu && (
          <div className="absolute bottom-[64px] left-3 right-3 animate-fade-in rounded-xl border border-surface-200 bg-white p-1 shadow-pop">
            <button
              onClick={() => {
                setUserMenu(false);
                nav(isAdminSection ? "/chat" : "/admin");
              }}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-[12.5px] text-ink-700 hover:bg-surface-100"
            >
              {isAdminSection ? <MessageSquare size={14} /> : <LayoutDashboard size={14} />}
              {isAdminSection ? "返回工作台" : "管理后台"}
            </button>
            <button
              onClick={async () => {
                await logout();
                nav("/login");
              }}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-[12.5px] text-rose-600 hover:bg-rose-50"
            >
              <LogOut size={14} /> 退出登录
            </button>
          </div>
        )}
      </div>
    </div>
  );

  return (
    <div className="flex h-full w-full overflow-hidden">
      <div className="hidden h-full lg:block">{sidebar}</div>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 flex lg:hidden">
          <div className="absolute inset-0 bg-ink-900/30" onClick={() => setMobileOpen(false)} />
          <div className="relative h-full">{sidebar}</div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-surface-300/70 bg-white/70 px-3 py-2 backdrop-blur lg:hidden">
          <button onClick={() => setMobileOpen(true)} className="rounded-lg p-1.5 text-ink-600 hover:bg-surface-100">
            <Menu size={18} />
          </button>
          <span className="text-[13px] font-medium">DataClaw</span>
          {isAdminSection && <Badge tone="brand">管理后台</Badge>}
        </div>
        <main className="min-h-0 flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
