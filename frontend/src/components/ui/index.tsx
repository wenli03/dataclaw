import React, { useEffect, useRef, useState } from "react";
import { cx, avatarPalette, initials } from "../../lib/format";
import { AlertCircle, Check, Info, Loader2, X } from "lucide-react";

/* ---------------- Button ---------------- */
type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "outline" | "ghost" | "danger" | "soft";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  icon?: React.ReactNode;
};
export function Button({ variant = "primary", size = "md", loading, icon, className, children, ...rest }: BtnProps) {
  const variants: Record<string, string> = {
    primary: "btn-primary",
    outline: "btn-outline",
    ghost: "btn-ghost",
    danger: "btn-danger",
    soft: "btn bg-brand-50 text-brand-700 hover:bg-brand-100",
  };
  const sizes: Record<string, string> = { sm: "!px-2.5 !py-1.5 !text-[12px]", md: "", lg: "!px-5 !py-2.5 !text-[14px]" };
  return (
    <button className={cx(variants[variant], sizes[size], className)} disabled={loading || rest.disabled} {...rest}>
      {loading ? <Loader2 size={14} className="animate-spin" /> : icon}
      {children}
    </button>
  );
}

/* ---------------- Card ---------------- */
export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("card", className)} {...rest}>
      {children}
    </div>
  );
}

export function CardHeader({ title, desc, extra, className }: { title: React.ReactNode; desc?: React.ReactNode; extra?: React.ReactNode; className?: string }) {
  return (
    <div className={cx("flex items-start justify-between gap-4 px-5 pt-4 pb-3", className)}>
      <div className="min-w-0">
        <div className="text-[14px] font-semibold text-ink-900">{title}</div>
        {desc && <div className="mt-0.5 text-[12px] text-ink-500">{desc}</div>}
      </div>
      {extra}
    </div>
  );
}

/* ---------------- Badge ---------------- */
export function Badge({
  children,
  tone = "gray",
  className,
  dot,
}: {
  children: React.ReactNode;
  tone?: "gray" | "brand" | "green" | "amber" | "rose" | "blue" | "teal";
  className?: string;
  dot?: boolean;
}) {
  const tones: Record<string, string> = {
    gray: "bg-surface-100 text-ink-600 border border-surface-300",
    brand: "bg-brand-50 text-brand-700 border border-brand-100",
    green: "bg-emerald-50 text-emerald-700 border border-emerald-100",
    amber: "bg-amber-50 text-amber-700 border border-amber-100",
    rose: "bg-rose-50 text-rose-700 border border-rose-100",
    blue: "bg-sky-50 text-sky-700 border border-sky-100",
    teal: "bg-teal-50 text-teal-700 border border-teal-100",
  };
  return (
    <span className={cx("chip whitespace-nowrap", tones[tone], className)}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />}
      {children}
    </span>
  );
}

/* ---------------- Inputs ---------------- */
export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...rest }, ref) => <input ref={ref} className={cx("input", className)} {...rest} />
);
Input.displayName = "Input";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...rest }, ref) => <textarea ref={ref} className={cx("input resize-y min-h-[80px]", className)} {...rest} />
);
Textarea.displayName = "Textarea";

export function Select({ className, children, ...rest }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cx("input pr-8 appearance-none bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2212%22 height=%2212%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%236B7280%22 stroke-width=%222%22><path d=%22M6 9l6 6 6-6%22/></svg>')] bg-[right_10px_center] bg-no-repeat", className)} {...rest}>
      {children}
    </select>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="label">{label}</label>
      {children}
      {hint && <div className="mt-1 text-[11px] text-ink-400">{hint}</div>}
    </div>
  );
}

export function Toggle({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        "relative h-5 w-9 rounded-full transition-colors disabled:opacity-50",
        checked ? "bg-brand-600" : "bg-surface-300"
      )}
    >
      <span
        className={cx(
          "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all",
          checked ? "left-[18px]" : "left-0.5"
        )}
      />
    </button>
  );
}

/* ---------------- Avatar ---------------- */
export function Avatar({ name, seed, size = 36, className, ring }: { name?: string; seed?: string; size?: number; className?: string; ring?: boolean }) {
  const { bg, fg } = avatarPalette(seed || name);
  return (
    <div
      className={cx("flex shrink-0 items-center justify-center rounded-full font-medium", ring && "ring-2 ring-white", className)}
      style={{ width: size, height: size, background: bg, color: fg, fontSize: size * 0.36 }}
      title={name}
    >
      {initials(name)}
    </div>
  );
}

/* ---------------- Modal / Drawer ---------------- */
export function Modal({
  open,
  onClose,
  title,
  desc,
  children,
  footer,
  width = "max-w-lg",
}: {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  desc?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-ink-900/30 backdrop-blur-[2px]" onClick={onClose} />
      <div className={cx("relative w-full animate-fade-in rounded-2xl bg-white shadow-pop", width)}>
        <div className="flex items-start justify-between gap-4 border-b border-surface-200 px-5 py-4">
          <div>
            <div className="text-[15px] font-semibold text-ink-900">{title}</div>
            {desc && <div className="mt-0.5 text-[12px] text-ink-500">{desc}</div>}
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-ink-400 hover:bg-surface-100 hover:text-ink-700">
            <X size={16} />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex items-center justify-end gap-2 border-t border-surface-200 px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Drawer({
  open,
  onClose,
  title,
  desc,
  children,
  footer,
  width = "w-[560px]",
}: {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  desc?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: string;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-ink-900/25 backdrop-blur-[1px]" onClick={onClose} />
      <div className={cx("absolute right-0 top-0 flex h-full max-w-[92vw] animate-slide-in flex-col bg-white shadow-pop", width)}>
        <div className="flex items-start justify-between gap-4 border-b border-surface-200 px-5 py-4">
          <div>
            <div className="text-[15px] font-semibold text-ink-900">{title}</div>
            {desc && <div className="mt-0.5 text-[12px] text-ink-500">{desc}</div>}
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-ink-400 hover:bg-surface-100 hover:text-ink-700">
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex items-center justify-end gap-2 border-t border-surface-200 px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

/* ---------------- Tabs ---------------- */
export function Tabs({
  items,
  value,
  onChange,
  className,
}: {
  items: { key: string; label: string; count?: number }[];
  value: string;
  onChange: (k: string) => void;
  className?: string;
}) {
  return (
    <div className={cx("flex items-center gap-1 rounded-xl bg-surface-100 p-1", className)}>
      {items.map((it) => (
        <button
          key={it.key}
          onClick={() => onChange(it.key)}
          className={cx(
            "rounded-lg px-3 py-1.5 text-[12.5px] font-medium transition-all",
            value === it.key ? "bg-white text-ink-900 shadow-sm" : "text-ink-500 hover:text-ink-800"
          )}
        >
          {it.label}
          {it.count !== undefined && <span className="ml-1 text-[11px] text-ink-400">{it.count}</span>}
        </button>
      ))}
    </div>
  );
}

/* ---------------- Empty / Loading ---------------- */
export function Empty({ title, desc, icon, action }: { title: string; desc?: string; icon?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-100 text-ink-400">
        {icon || <Info size={20} />}
      </div>
      <div className="text-[13.5px] font-medium text-ink-800">{title}</div>
      {desc && <div className="mt-1 max-w-md text-[12px] text-ink-500">{desc}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-[12.5px] text-ink-500">
      <Loader2 size={16} className="animate-spin" />
      {label || "加载中…"}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded-lg bg-surface-200", className)} />;
}

/* ---------------- Stat ---------------- */
export function Stat({ label, value, delta, icon, tone = "brand", hint }: { label: string; value: React.ReactNode; delta?: string; icon?: React.ReactNode; tone?: string; hint?: string }) {
  const tones: Record<string, string> = {
    brand: "bg-brand-50 text-brand-600",
    teal: "bg-teal-50 text-teal-600",
    amber: "bg-amber-50 text-amber-600",
    rose: "bg-rose-50 text-rose-600",
    sky: "bg-sky-50 text-sky-600",
  };
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[12px] text-ink-500">{label}</div>
          <div className="mt-1.5 text-[24px] font-semibold leading-none tracking-tight text-ink-900">{value}</div>
          {(delta || hint) && (
            <div className="mt-2 flex items-center gap-1.5 text-[11px] text-ink-500">
              {delta && <span className={cx("font-medium", delta.startsWith("-") ? "text-rose-600" : "text-emerald-600")}>{delta}</span>}
              {hint && <span>{hint}</span>}
            </div>
          )}
        </div>
        {icon && <div className={cx("flex h-9 w-9 items-center justify-center rounded-xl", tones[tone])}>{icon}</div>}
      </div>
    </Card>
  );
}

/* ---------------- Toast ---------------- */
type ToastMsg = { id: number; text: string; type: "success" | "error" | "info" };
let seq = 0;
const listeners = new Set<(m: ToastMsg) => void>();

export function toast(text: string, type: "success" | "error" | "info" = "success") {
  const msg = { id: ++seq, text, type };
  listeners.forEach((l) => l(msg));
}

export function ToastHost() {
  const [items, setItems] = useState<ToastMsg[]>([]);
  useEffect(() => {
    const listener = (m: ToastMsg) => {
      setItems((prev) => [...prev, m]);
      setTimeout(() => setItems((prev) => prev.filter((x) => x.id !== m.id)), 3200);
    };
    listeners.add(listener);
    return () => void listeners.delete(listener);
  }, []);
  const icons = { success: <Check size={13} />, error: <AlertCircle size={13} />, info: <Info size={13} /> };
  const colors = {
    success: "bg-emerald-600",
    error: "bg-rose-600",
    info: "bg-ink-900",
  };
  return (
    <div className="pointer-events-none fixed bottom-6 left-1/2 z-[100] flex -translate-x-1/2 flex-col items-center gap-2">
      {items.map((m) => (
        <div key={m.id} className={cx("animate-fade-in rounded-xl px-3.5 py-2 text-[12.5px] text-white shadow-pop", colors[m.type])}>
          <span className="mr-1.5 inline-flex align-[-2px]">{icons[m.type]}</span>
          {m.text}
        </div>
      ))}
    </div>
  );
}

/* ---------------- Simple Tooltip ---------------- */
export function Tip({ text, children }: { text: string; children: React.ReactNode }) {
  const [show, setShow] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  return (
    <span ref={ref} className="relative inline-flex" onMouseEnter={() => setShow(true)} onMouseLeave={() => setShow(false)}>
      {children}
      {show && (
        <span className="absolute -top-8 left-1/2 z-40 -translate-x-1/2 whitespace-nowrap rounded-lg bg-ink-900 px-2 py-1 text-[11px] text-white shadow-pop">
          {text}
        </span>
      )}
    </span>
  );
}
