import React from "react";
import { Check, ShieldAlert, X } from "lucide-react";
import { Button, Modal } from "../ui";
import { cx, riskBadgeClass, riskLabel } from "../../lib/format";

export type ApprovalRequest = {
  approvalId: string;
  stepId?: string;
  action: string;
  reason?: string;
  risk?: string;
};

const ACTION_LABEL: Record<string, string> = {
  export_docx: "导出带企业条款的修订版文件",
  export_report: "导出深度报告",
  export_file: "导出文件到本地",
  delete_file: "删除文件",
  write_database: "写入数据库",
  send_message: "对外发送消息",
  call_external: "调用外部接口",
  install_skill: "安装高风险技能",
};

export function ApprovalDialog({
  approval,
  busy,
  onDecide,
}: {
  approval: ApprovalRequest | null;
  busy?: boolean;
  onDecide: (decision: "approved" | "rejected") => void;
}) {
  if (!approval) return null;
  const risk = approval.risk || "high";
  return (
    <Modal
      open
      onClose={() => {
        /* 流处于挂起状态，必须做出决策：禁用静默关闭 */
      }}
      title="需要你的确认"
      desc="数字员工即将执行一项高风险动作，批准后才会继续。"
      width="max-w-md"
      footer={
        <>
          <Button variant="outline" onClick={() => onDecide("rejected")} disabled={busy} icon={<X size={14} />}>
            拒绝并跳过
          </Button>
          <Button onClick={() => onDecide("approved")} loading={busy} icon={<Check size={14} />}>
            批准并继续
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="flex items-start gap-2.5 rounded-xl border border-surface-200 bg-surface-50 px-3 py-2.5">
          <span className={cx("grid h-8 w-8 shrink-0 place-items-center rounded-xl border", riskBadgeClass(risk))}>
            <ShieldAlert size={15} />
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-[12.5px] font-medium text-ink-800">动作：{ACTION_LABEL[approval.action] || approval.action}</span>
              <span className={cx("chip border", riskBadgeClass(risk))}>{riskLabel[risk] || risk}</span>
            </div>
            <div className="mt-1 whitespace-pre-wrap break-words text-[12px] leading-relaxed text-ink-600">
              {approval.reason || "该操作可能影响企业数据安全，需人工确认。"}
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-dashed border-surface-300 px-3 py-2.5 text-[11.5px] leading-relaxed text-ink-500">
          批准后数字员工将继续执行；拒绝则跳过该步骤并在回答中说明。本次审批记录会写入审计日志（含审批人、时间与结果）。
        </div>
      </div>
    </Modal>
  );
}

export default ApprovalDialog;
