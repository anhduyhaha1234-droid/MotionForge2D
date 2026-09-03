"use client";

/**
 * S10-T04B — ApplyEvidenceLinks
 *
 * Exposes failed role/layer/segment reasons from the structural-compare
 * gate.  Only enables Review entry after the backend gate PASS.
 * Dark theme: VN helper text under every button, >= gray-400, >= 11px.
 */

const HELPER = "text-[11px] leading-snug text-gray-400";

export interface StructuralFailureView {
  code: string;
  reason: string;
  role: string;
  layer: string;
  segment: string;
  route: string;
  metric: string;
  value: unknown;
  threshold: unknown;
}

export interface StructuralEvidenceView {
  status: string;
  passed: boolean;
  failures: StructuralFailureView[];
  checks: Record<string, unknown>;
  policy_version: string | null;
  expected_policy_version: string | null;
}

interface ApplyEvidenceLinksProps {
  evidence: StructuralEvidenceView | null;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  onEnterReview?: () => void;
  reviewHref?: string;
}

export function ApplyEvidenceLinks({ evidence, loading, error, onRetry, onEnterReview, reviewHref }: ApplyEvidenceLinksProps) {
  if (loading) {
    return (
      <div className="rounded border border-gray-700 bg-gray-900/40 p-4" data-testid="apply-evidence-loading" aria-busy="true">
        <p className="text-sm text-gray-300">Đang kiểm tra cấu trúc…</p>
        <p className={HELPER}>Gọi POST /api/v2/full-apply/{"{run_id}"}/structural-compare và chờ kết quả.</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded border border-red-700 bg-red-900/20 p-4" role="alert" data-testid="apply-evidence-error">
        <p className="text-sm text-red-300">{error}</p>
        <p className={HELPER}>Lỗi khi gọi gate so sánh cấu trúc — kiểm tra run_id, policy hoặc dữ liệu đầu vào.</p>
        {onRetry && (
          <div className="mt-2 flex flex-col items-start gap-1">
            <button type="button" onClick={onRetry} className="rounded bg-red-700 px-3 py-1.5 text-xs text-white hover:bg-red-600" data-testid="apply-evidence-retry">
              Thử lại
            </button>
            <p className={HELPER}>Gửi lại yêu cầu structural-compare cho run hiện tại.</p>
          </div>
        )}
      </div>
    );
  }

  if (!evidence) {
    return (
      <div className="rounded border border-gray-700 bg-gray-900/40 p-4" data-testid="apply-evidence-empty">
        <p className="text-sm text-gray-400">Chưa có kết quả so sánh cấu trúc cho lần Apply này.</p>
        <p className={HELPER}>Nhấn Kiểm tra cấu trúc sau khi Apply hoàn tất để lấy bằng chứng role/layer/segment.</p>
      </div>
    );
  }

  const isBlocked = !evidence.passed || evidence.status === "BLOCKED";
  const canReview = !isBlocked && evidence.passed && evidence.status === "REVIEW_REQUIRED";

  return (
    <section className="rounded border border-gray-700 bg-gray-900/40 p-4" data-testid="apply-evidence" aria-label="Bằng chứng so sánh cấu trúc">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-100">Bằng chứng so sánh cấu trúc</h3>
          <p className={HELPER}>Kết quả từ POST /api/v2/full-apply/{"{run_id}"}/structural-compare — chặn REVIEW khi còn lỗi.</p>
        </div>
        <span
          className={`rounded px-2 py-0.5 text-xs font-medium ${isBlocked ? "bg-red-900/30 text-red-300" : "bg-emerald-900/20 text-emerald-300"}`}
          data-testid="apply-evidence-status"
        >
          {isBlocked ? "BLOCKED" : "REVIEW_REQUIRED"}
        </span>
      </div>

      {evidence.failures.length > 0 && (
        <div className="mt-3 space-y-2" data-testid="apply-evidence-failures">
          <p className="text-xs font-medium text-red-300">Lý do thất bại theo role/layer/segment (backend truth):</p>
          <ul className="space-y-1.5">
            {evidence.failures.map((f, idx) => (
              <li key={`${f.code}-${idx}`} className="rounded bg-red-900/10 px-2 py-1.5" data-testid={`apply-evidence-failure-${idx}`}>
                <p className="text-xs font-medium text-red-300">
                  <span className="font-mono">{f.code}</span> · {f.metric || "—"} · role {f.role} · layer {f.layer} · segment {f.segment} · route {f.route}
                </p>
                <p className="mt-0.5 text-xs text-gray-300">{f.reason}</p>
                {(f.value !== null && f.value !== undefined) || (f.threshold !== null && f.threshold !== undefined) ? (
                  <p className="mt-0.5 font-mono text-[11px] text-gray-400">
                    value: {JSON.stringify(f.value)} · threshold: {JSON.stringify(f.threshold)}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      )}

      {evidence.failures.length === 0 && !isBlocked && (
        <p className="mt-3 rounded bg-emerald-900/10 px-2 py-1.5 text-xs text-emerald-300" data-testid="apply-evidence-pass">
          Tất cả kiểm tra đã PASS — không có lỗi role/layer/segment nào bị chặn.
        </p>
      )}

      {Object.keys(evidence.checks).length > 0 && (
        <details className="mt-3 rounded bg-gray-800 px-2 py-1.5" data-testid="apply-evidence-checks">
          <summary className="cursor-pointer text-xs text-gray-300">Chi tiết checks (từ backend)</summary>
          <pre className="mt-1 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] text-gray-400">{JSON.stringify(evidence.checks, null, 2)}</pre>
        </details>
      )}

      <div className="mt-4 flex flex-col items-start gap-1">
        {reviewHref ? (
          <a
            href={reviewHref}
            aria-disabled={!canReview}
            onClick={(e) => {
              if (!canReview) e.preventDefault();
              else onEnterReview?.();
            }}
            className={`inline-flex min-h-9 items-center rounded px-4 py-1.5 text-sm font-medium ${canReview ? "bg-emerald-600 text-white hover:bg-emerald-500" : "pointer-events-none cursor-not-allowed bg-gray-700 text-gray-400 opacity-60"}`}
            data-testid="apply-review-link"
          >
            Mở trang kiểm tra (Review)
          </a>
        ) : (
          <button
            type="button"
            onClick={onEnterReview}
            disabled={!canReview}
            className={`inline-flex min-h-9 items-center rounded px-4 py-1.5 text-sm font-medium ${canReview ? "bg-emerald-600 text-white hover:bg-emerald-500" : "cursor-not-allowed bg-gray-700 text-gray-400"}`}
            data-testid="apply-review-btn"
          >
            Mở trang kiểm tra (Review)
          </button>
        )}
        <p className={HELPER}>
          {canReview ? "Gate đã PASS — đủ điều kiện vào luồng Review." : "Chỉ được vào Review sau khi gate trả về REVIEW_REQUIRED (không còn failure nào)."}
        </p>
      </div>

      {onRetry && (
        <div className="mt-2 flex flex-col items-start gap-1">
          <button type="button" onClick={onRetry} className="rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-700" data-testid="apply-evidence-refresh">
            Kiểm tra lại
          </button>
          <p className={HELPER}>Gửi lại yêu cầu structural-compare cho run hiện tại.</p>
        </div>
      )}
    </section>
  );
}
