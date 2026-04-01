"use client";

import type {
  GoogleBusinessProfileVerificationActionRequired,
  GoogleBusinessProfileVerificationMethodOption,
  GoogleBusinessProfileVerificationWorkflowState,
} from "../../lib/api/types";

interface VerificationStatusBadgeProps {
  state: GoogleBusinessProfileVerificationWorkflowState;
}

interface VerificationMethodsListProps {
  methods: GoogleBusinessProfileVerificationMethodOption[];
  selectedOptionId: string;
  onChange: (optionId: string) => void;
  disabled: boolean;
}

interface VerificationStartActionProps {
  onStart: () => void;
  onRetry: () => void;
  onRefresh: () => void;
  disabledStart: boolean;
  disabledRetry: boolean;
  disabledRefresh: boolean;
}

interface VerificationCodeEntryProps {
  code: string;
  actionRequired: GoogleBusinessProfileVerificationActionRequired;
  onCodeChange: (value: string) => void;
  onSubmit: () => void;
  disabled: boolean;
}

export function VerificationStatusBadge({ state }: VerificationStatusBadgeProps) {
  return <span className={`badge ${workflowBadgeClass(state)}`}>{workflowStateLabel(state)}</span>;
}

export function VerificationMethodsList({
  methods,
  selectedOptionId,
  onChange,
  disabled,
}: VerificationMethodsListProps) {
  if (methods.length === 0) {
    return <p className="hint muted">No verification methods are currently available for this location.</p>;
  }
  return (
    <label className="label-stack label-stack-medium">
      <span className="text-muted-small">Verification method</span>
      <select
        className="operator-select"
        value={selectedOptionId}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
      >
        <option value="">Select a method</option>
        {methods.map((method) => (
          <option key={method.option_id} value={method.option_id}>
            {method.label}
            {method.destination ? ` - ${method.destination}` : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

export function VerificationStartAction({
  onStart,
  onRetry,
  onRefresh,
  disabledStart,
  disabledRetry,
  disabledRefresh,
}: VerificationStartActionProps) {
  return (
    <div className="row-wrap-tight">
      <button className="primary" onClick={onStart} disabled={disabledStart}>
        Start verification
      </button>
      <button onClick={onRetry} disabled={disabledRetry}>
        Retry verification
      </button>
      <button onClick={onRefresh} disabled={disabledRefresh}>
        Refresh workflow
      </button>
    </div>
  );
}

export function VerificationCodeEntry({
  code,
  actionRequired,
  onCodeChange,
  onSubmit,
  disabled,
}: VerificationCodeEntryProps) {
  const showHint = actionRequired === "enter_code";
  return (
    <div className="stack-medium">
      <label className="label-stack label-stack-small">
        <span className="text-muted-small">Verification code</span>
        <input
          type="text"
          value={code}
          onChange={(event) => onCodeChange(event.target.value)}
          placeholder="Enter code"
          disabled={disabled}
        />
      </label>
      {showHint ? <p className="hint muted">This location requires a verification code to continue.</p> : null}
      <button onClick={onSubmit} disabled={disabled || !code.trim()}>
        Complete verification
      </button>
    </div>
  );
}

function workflowStateLabel(state: GoogleBusinessProfileVerificationWorkflowState): string {
  if (state === "completed") {
    return "Verified";
  }
  if (state === "pending") {
    return "Pending";
  }
  if (state === "in_progress") {
    return "In progress";
  }
  if (state === "failed") {
    return "Failed";
  }
  if (state === "unverified") {
    return "Not verified";
  }
  return "Unknown";
}

function workflowBadgeClass(state: GoogleBusinessProfileVerificationWorkflowState): string {
  if (state === "completed") {
    return "badge-success";
  }
  if (state === "pending" || state === "in_progress") {
    return "badge-warn";
  }
  if (state === "failed") {
    return "badge-error";
  }
  if (state === "unverified") {
    return "badge-muted";
  }
  return "badge-muted";
}
