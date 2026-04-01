import Link from "next/link";
import type { ActionControl } from "../../lib/api/types";

type ActionControlsProps = {
  controls: ActionControl[];
  resolveHref?: (control: ActionControl) => string | undefined;
  onAction?: (control: ActionControl) => void;
  className?: string;
  "data-testid"?: string;
};

function actionControlButtonClass(control: ActionControl): string {
  if (control.emphasis === "primary") {
    return "button button-primary button-inline";
  }
  if (control.emphasis === "secondary") {
    return "button button-secondary button-inline";
  }
  return "button button-tertiary button-inline";
}

export function ActionControls({
  controls,
  resolveHref,
  onAction,
  className = "",
  "data-testid": dataTestId,
}: ActionControlsProps) {
  if (!controls || controls.length === 0) {
    return null;
  }

  const wrapperClass = ["action-controls", className].filter(Boolean).join(" ");

  return (
    <div className={wrapperClass} data-testid={dataTestId}>
      {controls.map((control, index) => {
        const href = resolveHref ? resolveHref(control) : undefined;
        const itemTestId = dataTestId ? `${dataTestId}-control-${control.type}-${index}` : undefined;
        const reasonTestId = dataTestId ? `${dataTestId}-reason-${control.type}-${index}` : undefined;
        return (
          <div className="action-control-item" key={`${control.type}-${index}`}>
            {control.enabled ? (
              href ? (
                <Link href={href} className={actionControlButtonClass(control)} data-testid={itemTestId}>
                  {control.label}
                </Link>
              ) : (
                <button
                  type="button"
                  className={actionControlButtonClass(control)}
                  onClick={() => onAction?.(control)}
                  data-testid={itemTestId}
                >
                  {control.label}
                </button>
              )
            ) : (
              <button
                type="button"
                className={actionControlButtonClass(control)}
                disabled
                aria-disabled="true"
                data-testid={itemTestId}
              >
                {control.label}
              </button>
            )}
            {control.reason ? (
              <span className={`hint ${control.enabled ? "muted" : "warning"} action-control-reason`} data-testid={reasonTestId}>
                {control.reason}
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
