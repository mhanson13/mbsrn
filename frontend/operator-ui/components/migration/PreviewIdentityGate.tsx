"use client";

interface PreviewIdentityGateProps {
  previewHostname: string | null;
  previewSlugDraft: string;
  locked: boolean;
  busy: boolean;
  saving: boolean;
  unchanged: boolean;
  onChange: (value: string) => void;
  onSave: () => void;
}

export function PreviewIdentityGate({
  previewHostname,
  previewSlugDraft,
  locked,
  busy,
  saving,
  unchanged,
  onChange,
  onSave,
}: PreviewIdentityGateProps): JSX.Element {
  return (
    <div className="panel panel-compact stack-tight" data-testid="migration-preview-identity-gate">
      <strong>Preview domain · {previewHostname ? "Ready" : "Action required"}</strong>
      {previewHostname ? (
        <span className="hint success" data-testid="migration-preview-hostname">
          {previewHostname}
        </span>
      ) : (
        <span className="hint warning">
          Save the permanent site preview subdomain before approval, certificates, DNS, or deployment can begin.
        </span>
      )}
      <label className="stack-tight">
        <span className="hint muted">Preview subdomain</span>
        <input
          value={previewSlugDraft}
          onChange={(event) => onChange(event.target.value)}
          placeholder="example-site"
          disabled={busy || locked}
          data-testid="migration-preview-slug-input"
          aria-describedby="migration-preview-slug-guidance"
        />
      </label>
      <span className="hint muted" id="migration-preview-slug-guidance">
        {locked
          ? "This identity is locked because preview infrastructure has been created."
          : "The saved value becomes <subdomain>.site.mbsrn.com and is locked when preview infrastructure is first created."}
      </span>
      {!locked ? (
        <button
          type="button"
          className="button button-secondary"
          onClick={onSave}
          disabled={busy || !previewSlugDraft.trim() || unchanged}
          data-testid="migration-save-preview-identity-button"
        >
          {saving ? "Saving..." : "Save Preview Domain"}
        </button>
      ) : null}
    </div>
  );
}
