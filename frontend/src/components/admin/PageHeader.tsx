import React from "react";
import { cx } from "@/lib/format";

/**
 * 管理后台统一页头：标题 + 描述 + 右侧操作区。
 * 所有 admin 页面共用，保证「标题字号 / 间距 / 操作按钮位置」一致。
 */
export function PageHeader({
  title,
  desc,
  badge,
  meta,
  actions,
  className,
}: {
  title: React.ReactNode;
  desc?: React.ReactNode;
  /** 标题右侧的徽标（如「管理员视角」「只读」） */
  badge?: React.ReactNode;
  /** 描述下方的补充信息（更新于、统计口径等） */
  meta?: React.ReactNode;
  /** 右侧操作（按钮组） */
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("flex flex-wrap items-start justify-between gap-3", className)}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-[20px] font-semibold leading-tight tracking-tight text-ink-900">{title}</h1>
          {badge}
        </div>
        {desc && <p className="mt-1 max-w-3xl text-[12.5px] leading-relaxed text-ink-500">{desc}</p>}
        {meta && <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-ink-400">{meta}</div>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export default PageHeader;
