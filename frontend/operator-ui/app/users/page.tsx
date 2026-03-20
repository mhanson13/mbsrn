"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "../../components/AuthProvider";
import { useOperatorContext } from "../../components/useOperatorContext";
import {
  ApiRequestError,
  createPrincipal,
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
  const [principalId, setPrincipalId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<PrincipalRole>("operator");

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

  const handleCreateUser = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(null);

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

      {submitSuccess ? <p className="hint">{submitSuccess}</p> : null}
      {submitError ? <p className="hint error">{submitError}</p> : null}
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
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr key={`${user.business_id}:${user.id}`}>
              <td>{user.id}</td>
              <td>{user.display_name}</td>
              <td>{user.role}</td>
              <td>{user.is_active ? "yes" : "no"}</td>
              <td>{user.last_authenticated_at || "never"}</td>
              <td>
                {(identitiesByPrincipalId.get(user.id) || [])
                  .map((identity) => {
                    const label = identity.email || `${identity.provider}:${identity.provider_subject}`;
                    return identity.is_active ? label : `${label} (inactive)`;
                  })
                  .join(", ") || "none"}
              </td>
            </tr>
          ))}
          {!loadingUsers && users.length === 0 ? (
            <tr>
              <td colSpan={6}>No users found for this business.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </section>
  );
}
