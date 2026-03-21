"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "../../components/AuthProvider";
import { useOperatorContext } from "../../components/useOperatorContext";
import {
  activatePrincipalIdentity,
  activatePrincipal,
  ApiRequestError,
  createPrincipalIdentity,
  createPrincipal,
  deactivatePrincipalIdentity,
  deactivatePrincipal,
  fetchPrincipalIdentities,
  fetchPrincipals,
} from "../../lib/api/client";
import type { Principal, PrincipalIdentity, PrincipalRole } from "../../lib/api/types";

interface UsersLoadResult {
  users: Principal[];
  identities: PrincipalIdentity[];
  identityWarning: string | null;
}

function safeUsersErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "User administration is restricted to admin principals.";
    }
    if (error.status === 404) {
      return "Business scope was not found for this session.";
    }
  }
  return "Unable to load users right now. Please try again.";
}

function safeCreateUserErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to create users.";
    }
    if (error.status === 422) {
      return "Unable to create user. Check user id, role, and uniqueness.";
    }
  }
  return "Failed to create user.";
}

function safePrincipalActionErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to update users.";
    }
    if (error.status === 404) {
      return "User record not found in this business scope.";
    }
    if (error.status === 422) {
      return "Unable to update this user state. Ensure at least one active admin remains.";
    }
  }
  return "Failed to update user state.";
}

function safeIdentityActionErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to update sign-in identities.";
    }
    if (error.status === 404) {
      return "Sign-in identity not found in this business scope.";
    }
    if (error.status === 422) {
      return "Unable to update sign-in identity state.";
    }
  }
  return "Failed to update sign-in identity state.";
}

function safeCreateIdentityErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to create sign-in identities.";
    }
    if (error.status === 404) {
      return "Principal or business scope was not found.";
    }
    if (error.status === 422) {
      return "Unable to create sign-in identity. Verify provider, subject, and principal mapping.";
    }
  }
  return "Failed to create sign-in identity.";
}

function formatIdentityLabel(identity: PrincipalIdentity): string {
  return identity.email || `${identity.provider}:${identity.provider_subject}`;
}

export default function UsersPage() {
  const context = useOperatorContext();
  const { principal } = useAuth();
  const [users, setUsers] = useState<Principal[]>([]);
  const [identities, setIdentities] = useState<PrincipalIdentity[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [usersError, setUsersError] = useState<string | null>(null);
  const [identityWarning, setIdentityWarning] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [actingPrincipalId, setActingPrincipalId] = useState<string | null>(null);
  const [identityActionError, setIdentityActionError] = useState<string | null>(null);
  const [identityActionSuccess, setIdentityActionSuccess] = useState<string | null>(null);
  const [actingIdentityId, setActingIdentityId] = useState<string | null>(null);
  const [principalId, setPrincipalId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<PrincipalRole>("operator");
  const [identityPrincipalId, setIdentityPrincipalId] = useState("");
  const [identityProvider, setIdentityProvider] = useState("google");
  const [identityProviderSubject, setIdentityProviderSubject] = useState("");
  const [identityEmail, setIdentityEmail] = useState("");
  const [identityEmailVerified, setIdentityEmailVerified] = useState(false);
  const [identityIsActive, setIdentityIsActive] = useState(true);
  const [identitySubmitting, setIdentitySubmitting] = useState(false);
  const [identitySubmitError, setIdentitySubmitError] = useState<string | null>(null);
  const [identitySubmitSuccess, setIdentitySubmitSuccess] = useState<string | null>(null);

  const isAdmin = principal?.role === "admin";

  const loadUsersData = useCallback(async (): Promise<UsersLoadResult> => {
    const principalResponse = await fetchPrincipals(context.token, context.businessId);
    try {
      const identitiesResponse = await fetchPrincipalIdentities(context.token, context.businessId);
      return {
        users: principalResponse.items,
        identities: identitiesResponse.items,
        identityWarning: null,
      };
    } catch {
      return {
        users: principalResponse.items,
        identities: [],
        identityWarning: "Sign-in identity details are temporarily unavailable.",
      };
    }
  }, [context.businessId, context.token]);

  const identitiesByPrincipalId = useMemo(() => {
    const grouped = new Map<string, PrincipalIdentity[]>();
    for (const identity of identities) {
      const bucket = grouped.get(identity.principal_id);
      if (bucket) {
        bucket.push(identity);
      } else {
        grouped.set(identity.principal_id, [identity]);
      }
    }
    return grouped;
  }, [identities]);

  const activeUsersCount = useMemo(
    () => users.filter((user) => user.is_active).length,
    [users],
  );

  const principalsWithoutIdentityCount = useMemo(
    () =>
      users.filter((user) => {
        const userIdentities = identitiesByPrincipalId.get(user.id);
        return !userIdentities || userIdentities.length === 0;
      }).length,
    [identitiesByPrincipalId, users],
  );

  const normalizedIdentityProvider = useMemo(() => identityProvider.trim().toLowerCase(), [identityProvider]);
  const normalizedIdentityProviderSubject = useMemo(
    () => identityProviderSubject.trim(),
    [identityProviderSubject],
  );

  const existingIdentityForProviderSubject = useMemo(() => {
    if (!normalizedIdentityProvider || !normalizedIdentityProviderSubject) {
      return null;
    }
    return (
      identities.find(
        (identity) =>
          identity.provider === normalizedIdentityProvider &&
          identity.provider_subject === normalizedIdentityProviderSubject,
      ) || null
    );
  }, [identities, normalizedIdentityProvider, normalizedIdentityProviderSubject]);

  const identityAlreadyLinkedToSelectedPrincipal =
    existingIdentityForProviderSubject !== null &&
    existingIdentityForProviderSubject.principal_id === identityPrincipalId;

  const identityLinkedToDifferentPrincipal =
    existingIdentityForProviderSubject !== null &&
    existingIdentityForProviderSubject.principal_id !== identityPrincipalId;

  useEffect(() => {
    if (context.loading || context.error || !isAdmin) {
      return;
    }

    let cancelled = false;
    async function loadUsers() {
      setLoadingUsers(true);
      setUsersError(null);
      setIdentityWarning(null);
      try {
        const result = await loadUsersData();
        if (!cancelled) {
          setUsers(result.users);
          setIdentities(result.identities);
          setIdentityWarning(result.identityWarning);
        }
      } catch (err) {
        if (!cancelled) {
          setUsersError(safeUsersErrorMessage(err));
        }
      } finally {
        if (!cancelled) {
          setLoadingUsers(false);
        }
      }
    }

    void loadUsers();
    return () => {
      cancelled = true;
    };
  }, [context.error, context.loading, isAdmin, loadUsersData]);

  useEffect(() => {
    if (users.length === 0) {
      if (identityPrincipalId !== "") {
        setIdentityPrincipalId("");
      }
      return;
    }

    const selectedPrincipalExists = users.some((user) => user.id === identityPrincipalId);
    if (!selectedPrincipalExists) {
      setIdentityPrincipalId(users[0].id);
    }
  }, [identityPrincipalId, users]);

  const handleCreateUser = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(null);
    setIdentitySubmitError(null);
    setIdentitySubmitSuccess(null);
    setActionError(null);
    setActionSuccess(null);
    setIdentityActionError(null);
    setIdentityActionSuccess(null);

    try {
      await createPrincipal(context.token, context.businessId, {
        principal_id: principalId.trim(),
        display_name: displayName.trim() || undefined,
        role,
      });
      const refreshed = await loadUsersData();
      setUsers(refreshed.users);
      setIdentities(refreshed.identities);
      setIdentityWarning(refreshed.identityWarning);
      setPrincipalId("");
      setDisplayName("");
      setRole("operator");
      setSubmitSuccess("User record created.");
    } catch (err) {
      setSubmitError(safeCreateUserErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleCreateAndLinkIdentity = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIdentitySubmitError(null);
    setIdentitySubmitSuccess(null);
    setSubmitError(null);
    setSubmitSuccess(null);
    setActionError(null);
    setActionSuccess(null);
    setIdentityActionError(null);
    setIdentityActionSuccess(null);

    if (!identityPrincipalId.trim()) {
      setIdentitySubmitError("Select a principal to link this identity.");
      return;
    }
    if (!normalizedIdentityProvider) {
      setIdentitySubmitError("Provider is required.");
      return;
    }
    if (!normalizedIdentityProviderSubject) {
      setIdentitySubmitError("Provider subject is required.");
      return;
    }
    if (identityAlreadyLinkedToSelectedPrincipal) {
      setIdentitySubmitError("This identity is already linked to the selected principal.");
      return;
    }
    if (identityLinkedToDifferentPrincipal) {
      setIdentitySubmitError(
        `This identity is already linked to principal "${existingIdentityForProviderSubject?.principal_id}".`,
      );
      return;
    }

    setIdentitySubmitting(true);
    try {
      await createPrincipalIdentity(context.token, context.businessId, {
        provider: normalizedIdentityProvider,
        provider_subject: normalizedIdentityProviderSubject,
        principal_id: identityPrincipalId.trim(),
        email: identityEmail.trim() || undefined,
        email_verified: identityEmailVerified,
        is_active: identityIsActive,
      });
      const refreshed = await loadUsersData();
      setUsers(refreshed.users);
      setIdentities(refreshed.identities);
      setIdentityWarning(refreshed.identityWarning);
      setIdentityProviderSubject("");
      setIdentityEmail("");
      setIdentityEmailVerified(false);
      setIdentityIsActive(true);
      setIdentitySubmitSuccess(`Identity linked to principal "${identityPrincipalId.trim()}".`);
    } catch (err) {
      setIdentitySubmitError(safeCreateIdentityErrorMessage(err));
    } finally {
      setIdentitySubmitting(false);
    }
  };

  const handleToggleUserActive = async (user: Principal) => {
    const activating = !user.is_active;
    const actionLabel = activating ? "reactivate" : "deactivate";
    const confirmed = window.confirm(
      `Confirm ${actionLabel} for user "${user.id}"? This updates business access immediately.`,
    );
    if (!confirmed) {
      return;
    }

    setActionError(null);
    setActionSuccess(null);
    setActingPrincipalId(user.id);
    setIdentityActionError(null);
    setIdentityActionSuccess(null);
    setSubmitError(null);
    setSubmitSuccess(null);
    setIdentitySubmitError(null);
    setIdentitySubmitSuccess(null);
    try {
      if (activating) {
        await activatePrincipal(context.token, context.businessId, user.id);
      } else {
        await deactivatePrincipal(context.token, context.businessId, user.id);
      }
      const refreshed = await loadUsersData();
      setUsers(refreshed.users);
      setIdentities(refreshed.identities);
      setIdentityWarning(refreshed.identityWarning);
      setActionSuccess(
        activating ? `User ${user.id} reactivated.` : `User ${user.id} deactivated.`,
      );
    } catch (err) {
      setActionError(safePrincipalActionErrorMessage(err));
    } finally {
      setActingPrincipalId(null);
    }
  };

  const handleToggleIdentityActive = async (identity: PrincipalIdentity) => {
    const activating = !identity.is_active;
    const actionLabel = activating ? "reactivate" : "deactivate";
    const identityLabel = formatIdentityLabel(identity);
    const confirmed = window.confirm(
      `Confirm ${actionLabel} sign-in identity "${identityLabel}" for principal "${identity.principal_id}"?`,
    );
    if (!confirmed) {
      return;
    }

    setIdentityActionError(null);
    setIdentityActionSuccess(null);
    setActingIdentityId(identity.id);
    setActionError(null);
    setActionSuccess(null);
    setSubmitError(null);
    setSubmitSuccess(null);
    setIdentitySubmitError(null);
    setIdentitySubmitSuccess(null);
    try {
      if (activating) {
        await activatePrincipalIdentity(context.token, context.businessId, identity.id);
      } else {
        await deactivatePrincipalIdentity(context.token, context.businessId, identity.id);
      }
      const refreshed = await loadUsersData();
      setUsers(refreshed.users);
      setIdentities(refreshed.identities);
      setIdentityWarning(refreshed.identityWarning);
      setIdentityActionSuccess(
        activating
          ? `Identity ${identityLabel} reactivated.`
          : `Identity ${identityLabel} deactivated.`,
      );
    } catch (err) {
      setIdentityActionError(safeIdentityActionErrorMessage(err));
    } finally {
      setActingIdentityId(null);
    }
  };

  if (context.loading) {
    return <section className="panel">Loading users...</section>;
  }
  if (context.error) {
    return <section className="panel">Error: {context.error}</section>;
  }
  if (!isAdmin) {
    return (
      <section className="panel stack">
        <h1>Users</h1>
        <p className="hint muted">User administration is available to admin principals only.</p>
      </section>
    );
  }

  return (
    <section className="panel stack">
      <h1>Users</h1>
      <p>
        Business: <code>{context.businessId}</code>
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
        <span className="hint muted">Principals: {users.length}</span>
        <span className="hint muted">Active Principals: {activeUsersCount}</span>
        <span className="hint muted">Sign-In Identities: {identities.length}</span>
        <span className="hint muted">Principals Without Identity: {principalsWithoutIdentityCount}</span>
      </div>

      <form onSubmit={(event) => void handleCreateUser(event)} className="stack">
        <h2>Create User</h2>
        <label htmlFor="principal-id">User ID</label>
        <input
          id="principal-id"
          value={principalId}
          onChange={(event) => setPrincipalId(event.target.value)}
          placeholder="user@example.com"
          required
        />

        <label htmlFor="display-name">Display Name (optional)</label>
        <input
          id="display-name"
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          placeholder="Operator Name"
        />

        <label htmlFor="user-role">Role</label>
        <select id="user-role" value={role} onChange={(event) => setRole(event.target.value as PrincipalRole)}>
          <option value="operator">operator</option>
          <option value="admin">admin</option>
        </select>

        <button className="primary" type="submit" disabled={submitting}>
          {submitting ? "Creating..." : "Create User"}
        </button>
      </form>

      <form onSubmit={(event) => void handleCreateAndLinkIdentity(event)} className="stack">
        <h2>Create and Link Identity</h2>
        <p className="hint muted">
          Each sign-in identity maps to exactly one principal in this business.
        </p>

        <label htmlFor="identity-principal">Principal</label>
        <select
          id="identity-principal"
          value={identityPrincipalId}
          onChange={(event) => setIdentityPrincipalId(event.target.value)}
          required
          disabled={users.length === 0 || identitySubmitting}
        >
          {users.length === 0 ? <option value="">No principals available</option> : null}
          {users.map((user) => (
            <option key={user.id} value={user.id}>
              {user.id} ({user.role})
            </option>
          ))}
        </select>

        <label htmlFor="identity-provider">Provider</label>
        <input
          id="identity-provider"
          value={identityProvider}
          onChange={(event) => setIdentityProvider(event.target.value)}
          placeholder="google"
          required
          disabled={identitySubmitting}
        />

        <label htmlFor="identity-provider-subject">Provider Subject</label>
        <input
          id="identity-provider-subject"
          value={identityProviderSubject}
          onChange={(event) => setIdentityProviderSubject(event.target.value)}
          placeholder="provider subject"
          required
          disabled={identitySubmitting}
        />

        <label htmlFor="identity-email">Email (optional)</label>
        <input
          id="identity-email"
          value={identityEmail}
          onChange={(event) => setIdentityEmail(event.target.value)}
          placeholder="user@example.com"
          disabled={identitySubmitting}
        />

        <label htmlFor="identity-email-verified" style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
          <input
            id="identity-email-verified"
            type="checkbox"
            checked={identityEmailVerified}
            onChange={(event) => setIdentityEmailVerified(event.target.checked)}
            disabled={identitySubmitting}
          />
          Email verified
        </label>

        <label htmlFor="identity-is-active" style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
          <input
            id="identity-is-active"
            type="checkbox"
            checked={identityIsActive}
            onChange={(event) => setIdentityIsActive(event.target.checked)}
            disabled={identitySubmitting}
          />
          Identity active
        </label>

        {identityAlreadyLinkedToSelectedPrincipal ? (
          <p className="hint warning">This identity is already linked to the selected principal.</p>
        ) : null}
        {identityLinkedToDifferentPrincipal ? (
          <p className="hint warning">
            This identity is already linked to principal{" "}
            <code>{existingIdentityForProviderSubject?.principal_id}</code>.
          </p>
        ) : null}

        <button
          className="primary"
          type="submit"
          disabled={
            identitySubmitting ||
            users.length === 0 ||
            identityAlreadyLinkedToSelectedPrincipal ||
            identityLinkedToDifferentPrincipal
          }
        >
          {identitySubmitting ? "Creating and Linking..." : "Create and Link Identity"}
        </button>
      </form>

      {submitSuccess ? <p className="hint">{submitSuccess}</p> : null}
      {submitError ? <p className="hint error">{submitError}</p> : null}
      {identitySubmitSuccess ? <p className="hint">{identitySubmitSuccess}</p> : null}
      {identitySubmitError ? <p className="hint error">{identitySubmitError}</p> : null}
      {actionSuccess ? <p className="hint">Principal action: {actionSuccess}</p> : null}
      {actionError ? <p className="hint error">Principal action: {actionError}</p> : null}
      {identityActionSuccess ? <p className="hint">Identity action: {identityActionSuccess}</p> : null}
      {identityActionError ? <p className="hint error">Identity action: {identityActionError}</p> : null}
      {loadingUsers ? <p className="hint muted">Loading users...</p> : null}
      {usersError ? <p className="hint error">{usersError}</p> : null}
      {identityWarning ? <p className="hint warning">{identityWarning}</p> : null}
      {!loadingUsers && users.length > 0 && principalsWithoutIdentityCount > 0 ? (
        <p className="hint muted">
          Some principals have no mapped sign-in identity yet. They will not be able to authenticate until an identity is linked.
        </p>
      ) : null}

      <table className="table">
        <thead>
          <tr>
            <th>User ID</th>
            <th>Display Name</th>
            <th>Role</th>
            <th>Active</th>
            <th>Last Auth</th>
            <th>Sign-In Identities</th>
            <th>Identity Actions</th>
            <th>Principal Action</th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => {
            const userIdentities = identitiesByPrincipalId.get(user.id) || [];
            return (
              <tr key={`${user.business_id}:${user.id}`}>
                <td>{user.id}</td>
                <td>{user.display_name}</td>
                <td>{user.role}</td>
                <td>{user.is_active ? "yes" : "no"}</td>
                <td>{user.last_authenticated_at || "never"}</td>
                <td>
                  {userIdentities.length === 0 ? (
                    "none"
                  ) : (
                    <ul style={{ margin: 0, paddingInlineStart: "1.25rem" }}>
                      {userIdentities.map((identity) => (
                        <li key={identity.id}>
                          {formatIdentityLabel(identity)} ({identity.is_active ? "active" : "inactive"})
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
                <td>
                  {userIdentities.length === 0 ? (
                    "none"
                  ) : (
                    <div style={{ display: "grid", gap: "0.4rem" }}>
                      {userIdentities.map((identity) => (
                        <button
                          key={identity.id}
                          type="button"
                          disabled={!!actingIdentityId || !!actingPrincipalId}
                          onClick={() => {
                            void handleToggleIdentityActive(identity);
                          }}
                        >
                          {actingIdentityId === identity.id
                            ? identity.is_active
                              ? "Deactivating Identity..."
                              : "Reactivating Identity..."
                            : identity.is_active
                              ? "Deactivate Identity"
                              : "Reactivate Identity"}
                        </button>
                      ))}
                    </div>
                  )}
                </td>
                <td>
                  <button
                    type="button"
                    disabled={!!actingPrincipalId || !!actingIdentityId}
                    onClick={() => {
                      void handleToggleUserActive(user);
                    }}
                  >
                    {actingPrincipalId === user.id
                      ? user.is_active
                        ? "Deactivating..."
                        : "Reactivating..."
                      : user.is_active
                        ? "Deactivate"
                        : "Reactivate"}
                  </button>
                </td>
              </tr>
            );
          })}
          {!loadingUsers && users.length === 0 ? (
            <tr>
              <td colSpan={8}>No users found for this business.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </section>
  );
}
