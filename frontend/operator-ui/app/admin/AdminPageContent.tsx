"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "../../components/AuthProvider";
import { FormContainer } from "../../components/layout/FormContainer";
import { PageContainer } from "../../components/layout/PageContainer";
import { SectionCard } from "../../components/layout/SectionCard";
import { useOperatorContext } from "../../components/useOperatorContext";
import {
  activatePrincipalIdentity,
  activatePrincipal,
  ApiRequestError,
  createPrincipalIdentity,
  createPrincipal,
  deactivatePrincipalIdentity,
  deactivatePrincipal,
  fetchBusinessSettings,
  fetchPrincipalIdentities,
  fetchPrincipals,
  updateBusinessSettings,
} from "../../lib/api/client";
import type { BusinessSettings, Principal, PrincipalIdentity, PrincipalRole } from "../../lib/api/types";
import {
  COMPETITOR_BIG_BOX_PENALTY_MAX,
  COMPETITOR_BIG_BOX_PENALTY_MIN,
  COMPETITOR_DIRECTORY_PENALTY_MAX,
  COMPETITOR_DIRECTORY_PENALTY_MIN,
  COMPETITOR_LOCAL_ALIGNMENT_BONUS_MAX,
  COMPETITOR_LOCAL_ALIGNMENT_BONUS_MIN,
  COMPETITOR_MIN_RELEVANCE_SCORE_MAX,
  COMPETITOR_MIN_RELEVANCE_SCORE_MIN,
  CRAWL_PAGE_LIMIT_MAX,
  CRAWL_PAGE_LIMIT_MIN,
  DEFAULT_CRAWL_PAGE_LIMIT,
  NOTIFICATION_EMAIL_REGEX,
  NOTIFICATION_PHONE_E164_REGEX,
} from "../../lib/validation/constants";

interface AdminPageLoadResult {
  users: Principal[];
  identities: PrincipalIdentity[];
  identityWarning: string | null;
}

type SettingsSectionHealthStatus = "valid" | "invalid";

interface SettingsSectionHealth {
  status: SettingsSectionHealthStatus;
  message: string | null;
}

interface SettingsHealthSummary {
  crawl: SettingsSectionHealth;
  competitorQuality: SettingsSectionHealth;
  notifications: SettingsSectionHealth;
}

function parseBoundedInteger(input: string, bounds: { min: number; max: number }): number | null {
  const normalized = input.trim();
  if (!/^\d+$/.test(normalized)) {
    return null;
  }

  const parsed = Number(normalized);
  if (!Number.isSafeInteger(parsed)) {
    return null;
  }
  if (parsed < bounds.min || parsed > bounds.max) {
    return null;
  }
  return parsed;
}

function parseCrawlPageLimit(input: string): number | null {
  return parseBoundedInteger(input, {
    min: CRAWL_PAGE_LIMIT_MIN,
    max: CRAWL_PAGE_LIMIT_MAX,
  });
}

function isBoundedIntegerValue(value: number, bounds: { min: number; max: number }): boolean {
  if (!Number.isSafeInteger(value)) {
    return false;
  }
  return value >= bounds.min && value <= bounds.max;
}

function isValidNotificationPhone(value: string | null): boolean {
  if (!value) {
    return false;
  }
  return NOTIFICATION_PHONE_E164_REGEX.test(value.trim());
}

function isValidNotificationEmail(value: string | null): boolean {
  if (!value) {
    return false;
  }
  return NOTIFICATION_EMAIL_REGEX.test(value.trim());
}

function evaluateSettingsHealth(settings: BusinessSettings | null): SettingsHealthSummary {
  if (!settings) {
    return {
      crawl: { status: "valid", message: null },
      competitorQuality: { status: "valid", message: null },
      notifications: { status: "valid", message: null },
    };
  }

  const crawlIsValid = isBoundedIntegerValue(settings.seo_audit_crawl_max_pages, {
    min: CRAWL_PAGE_LIMIT_MIN,
    max: CRAWL_PAGE_LIMIT_MAX,
  });

  const competitorQualityIsValid =
    isBoundedIntegerValue(settings.competitor_candidate_min_relevance_score, {
      min: COMPETITOR_MIN_RELEVANCE_SCORE_MIN,
      max: COMPETITOR_MIN_RELEVANCE_SCORE_MAX,
    }) &&
    isBoundedIntegerValue(settings.competitor_candidate_big_box_penalty, {
      min: COMPETITOR_BIG_BOX_PENALTY_MIN,
      max: COMPETITOR_BIG_BOX_PENALTY_MAX,
    }) &&
    isBoundedIntegerValue(settings.competitor_candidate_directory_penalty, {
      min: COMPETITOR_DIRECTORY_PENALTY_MIN,
      max: COMPETITOR_DIRECTORY_PENALTY_MAX,
    }) &&
    isBoundedIntegerValue(settings.competitor_candidate_local_alignment_bonus, {
      min: COMPETITOR_LOCAL_ALIGNMENT_BONUS_MIN,
      max: COMPETITOR_LOCAL_ALIGNMENT_BONUS_MAX,
    });

  const smsEnabled = settings.sms_enabled;
  const emailEnabled = settings.email_enabled;
  const smsChannelUsable = smsEnabled && isValidNotificationPhone(settings.notification_phone);
  const emailChannelUsable = emailEnabled && isValidNotificationEmail(settings.notification_email);
  const notificationsAreValid =
    (!smsEnabled || smsChannelUsable) &&
    (!emailEnabled || emailChannelUsable) &&
    (!settings.contractor_alerts_enabled || smsChannelUsable || emailChannelUsable) &&
    (!settings.customer_auto_ack_enabled || smsEnabled || emailEnabled);

  return {
    crawl: {
      status: crawlIsValid ? "valid" : "invalid",
      message: crawlIsValid ? null : "Saved value is outside the allowed range.",
    },
    competitorQuality: {
      status: competitorQualityIsValid ? "valid" : "invalid",
      message: competitorQualityIsValid ? null : "One or more saved values need review.",
    },
    notifications: {
      status: notificationsAreValid ? "valid" : "invalid",
      message: notificationsAreValid ? null : "One or more saved values need review.",
    },
  };
}

function safeAdminPageErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "Business administration is restricted to admin principals.";
    }
    if (error.status === 404) {
      return "Business scope was not found for this session.";
    }
  }
  return "Unable to load admin data right now. Please try again.";
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

function safeBusinessSettingsErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view business settings.";
    }
    if (error.status === 404) {
      return "Business settings were not found in this tenant scope.";
    }
  }
  return "Unable to load business settings right now.";
}

function apiErrorMessageContains(error: ApiRequestError, token: string): boolean {
  return error.message.toLowerCase().includes(token.toLowerCase());
}

function safeBusinessSettingsUpdateErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "Only admin principals can update crawl settings.";
    }
    if (error.status === 404) {
      return "Business settings were not found in this tenant scope.";
    }
    if (error.status === 422) {
      if (apiErrorMessageContains(error, "seo_audit_crawl_max_pages")) {
        return `Crawl page limit must be between ${CRAWL_PAGE_LIMIT_MIN} and ${CRAWL_PAGE_LIMIT_MAX}.`;
      }
      return "Unable to save SEO crawl settings. Please review the entered crawl limit.";
    }
  }
  return "Failed to update crawl page limit.";
}

function safeCandidateQualitySettingsUpdateErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "Only admin principals can update competitor quality tuning.";
    }
    if (error.status === 404) {
      return "Business settings were not found in this tenant scope.";
    }
    if (error.status === 422) {
      // Section-scoped settings saves should map backend validation to the
      // relevant section fields and otherwise use a safe fallback.
      if (apiErrorMessageContains(error, "competitor_candidate_min_relevance_score")) {
        return (
          "Minimum relevance score must be an integer between " +
          `${COMPETITOR_MIN_RELEVANCE_SCORE_MIN} and ${COMPETITOR_MIN_RELEVANCE_SCORE_MAX}.`
        );
      }
      if (apiErrorMessageContains(error, "competitor_candidate_big_box_penalty")) {
        return (
          "Big-box mismatch penalty must be an integer between " +
          `${COMPETITOR_BIG_BOX_PENALTY_MIN} and ${COMPETITOR_BIG_BOX_PENALTY_MAX}.`
        );
      }
      if (apiErrorMessageContains(error, "competitor_candidate_directory_penalty")) {
        return (
          "Directory/aggregator penalty must be an integer between " +
          `${COMPETITOR_DIRECTORY_PENALTY_MIN} and ${COMPETITOR_DIRECTORY_PENALTY_MAX}.`
        );
      }
      if (apiErrorMessageContains(error, "competitor_candidate_local_alignment_bonus")) {
        return (
          "Local alignment bonus must be an integer between " +
          `${COMPETITOR_LOCAL_ALIGNMENT_BONUS_MIN} and ${COMPETITOR_LOCAL_ALIGNMENT_BONUS_MAX}.`
        );
      }
      return "Unable to save this settings section. Please review the entered values.";
    }
  }
  return "Failed to update competitor quality settings.";
}

function safePromptSettingsUpdateErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "Only admin principals can update AI prompt overrides.";
    }
    if (error.status === 404) {
      return "Business settings were not found in this tenant scope.";
    }
    if (error.status === 422) {
      return "Unable to save AI prompt overrides. Keep each prompt under 20,000 characters.";
    }
  }
  return "Failed to update AI prompt overrides.";
}

function normalizePromptOverrideInput(value: string): string | null {
  const normalized = value.trim();
  if (!normalized) {
    return null;
  }
  return normalized;
}

function formatIdentityLabel(identity: PrincipalIdentity): string {
  return identity.email || `${identity.provider}:${identity.provider_subject}`;
}

export default function AdminPage() {
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
  const [businessSettings, setBusinessSettings] = useState<BusinessSettings | null>(null);
  const [businessSettingsLoading, setBusinessSettingsLoading] = useState(false);
  const [businessSettingsLoadError, setBusinessSettingsLoadError] = useState<string | null>(null);
  const [crawlPageLimitInput, setCrawlPageLimitInput] = useState(String(DEFAULT_CRAWL_PAGE_LIMIT));
  const [crawlPageLimitSubmitting, setCrawlPageLimitSubmitting] = useState(false);
  const [crawlPageLimitMessage, setCrawlPageLimitMessage] = useState<string | null>(null);
  const [crawlPageLimitError, setCrawlPageLimitError] = useState<string | null>(null);
  const [candidateMinRelevanceScoreInput, setCandidateMinRelevanceScoreInput] = useState("35");
  const [candidateBigBoxPenaltyInput, setCandidateBigBoxPenaltyInput] = useState("20");
  const [candidateDirectoryPenaltyInput, setCandidateDirectoryPenaltyInput] = useState("35");
  const [candidateLocalAlignmentBonusInput, setCandidateLocalAlignmentBonusInput] = useState("10");
  const [candidateQualitySubmitting, setCandidateQualitySubmitting] = useState(false);
  const [candidateQualityMessage, setCandidateQualityMessage] = useState<string | null>(null);
  const [candidateQualityError, setCandidateQualityError] = useState<string | null>(null);
  const [competitorPromptOverrideInput, setCompetitorPromptOverrideInput] = useState("");
  const [recommendationsPromptOverrideInput, setRecommendationsPromptOverrideInput] = useState("");
  const [promptOverrideSubmitting, setPromptOverrideSubmitting] = useState(false);
  const [promptOverrideMessage, setPromptOverrideMessage] = useState<string | null>(null);
  const [promptOverrideError, setPromptOverrideError] = useState<string | null>(null);

  const isAdmin = principal?.role === "admin";

  const loadUsersData = useCallback(async (): Promise<AdminPageLoadResult> => {
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
  const settingsHealth = useMemo(
    () => evaluateSettingsHealth(businessSettings),
    [businessSettings],
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
          setUsersError(safeAdminPageErrorMessage(err));
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
    if (context.loading || context.error || !isAdmin) {
      return;
    }

    let cancelled = false;

    async function loadBusinessSettings() {
      setBusinessSettingsLoading(true);
      setBusinessSettingsLoadError(null);
      try {
        const settings = await fetchBusinessSettings(context.token, context.businessId);
        if (cancelled) {
          return;
        }
        setBusinessSettings(settings);
        setCrawlPageLimitInput(String(settings.seo_audit_crawl_max_pages));
        setCandidateMinRelevanceScoreInput(String(settings.competitor_candidate_min_relevance_score));
        setCandidateBigBoxPenaltyInput(String(settings.competitor_candidate_big_box_penalty));
        setCandidateDirectoryPenaltyInput(String(settings.competitor_candidate_directory_penalty));
        setCandidateLocalAlignmentBonusInput(String(settings.competitor_candidate_local_alignment_bonus));
        setCompetitorPromptOverrideInput(settings.ai_prompt_text_competitor || "");
        setRecommendationsPromptOverrideInput(settings.ai_prompt_text_recommendations || "");
      } catch (err) {
        if (!cancelled) {
          setBusinessSettingsLoadError(safeBusinessSettingsErrorMessage(err));
        }
      } finally {
        if (!cancelled) {
          setBusinessSettingsLoading(false);
        }
      }
    }

    void loadBusinessSettings();
    return () => {
      cancelled = true;
    };
  }, [context.businessId, context.error, context.loading, context.token, isAdmin]);

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

  const handleUpdateCrawlPageLimit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCrawlPageLimitMessage(null);
    setCrawlPageLimitError(null);

    const parsed = parseCrawlPageLimit(crawlPageLimitInput);
    if (parsed === null) {
      setCrawlPageLimitError(
        `Crawl page limit must be an integer between ${CRAWL_PAGE_LIMIT_MIN} and ${CRAWL_PAGE_LIMIT_MAX}.`,
      );
      return;
    }

    setCrawlPageLimitSubmitting(true);
    try {
      const updated = await updateBusinessSettings(context.token, context.businessId, {
        seo_audit_crawl_max_pages: parsed,
      });
      setBusinessSettings(updated);
      setCrawlPageLimitInput(String(updated.seo_audit_crawl_max_pages));
      setCrawlPageLimitMessage(`SEO crawl page limit updated to ${updated.seo_audit_crawl_max_pages}.`);
    } catch (err) {
      setCrawlPageLimitError(safeBusinessSettingsUpdateErrorMessage(err));
    } finally {
      setCrawlPageLimitSubmitting(false);
    }
  };

  const handleUpdateCompetitorCandidateQuality = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCandidateQualityError(null);
    setCrawlPageLimitMessage(null);
    setCandidateQualityMessage(null);
    setPromptOverrideMessage(null);

    const minRelevanceScore = parseBoundedInteger(candidateMinRelevanceScoreInput, {
      min: COMPETITOR_MIN_RELEVANCE_SCORE_MIN,
      max: COMPETITOR_MIN_RELEVANCE_SCORE_MAX,
    });
    if (minRelevanceScore === null) {
      setCandidateQualityError(
        (
          "Minimum relevance score must be an integer between " +
          `${COMPETITOR_MIN_RELEVANCE_SCORE_MIN} and ${COMPETITOR_MIN_RELEVANCE_SCORE_MAX}.`
        ),
      );
      return;
    }

    const bigBoxPenalty = parseBoundedInteger(candidateBigBoxPenaltyInput, {
      min: COMPETITOR_BIG_BOX_PENALTY_MIN,
      max: COMPETITOR_BIG_BOX_PENALTY_MAX,
    });
    if (bigBoxPenalty === null) {
      setCandidateQualityError(
        (
          "Big-box mismatch penalty must be an integer between " +
          `${COMPETITOR_BIG_BOX_PENALTY_MIN} and ${COMPETITOR_BIG_BOX_PENALTY_MAX}.`
        ),
      );
      return;
    }

    const directoryPenalty = parseBoundedInteger(candidateDirectoryPenaltyInput, {
      min: COMPETITOR_DIRECTORY_PENALTY_MIN,
      max: COMPETITOR_DIRECTORY_PENALTY_MAX,
    });
    if (directoryPenalty === null) {
      setCandidateQualityError(
        (
          "Directory/aggregator penalty must be an integer between " +
          `${COMPETITOR_DIRECTORY_PENALTY_MIN} and ${COMPETITOR_DIRECTORY_PENALTY_MAX}.`
        ),
      );
      return;
    }

    const localAlignmentBonus = parseBoundedInteger(candidateLocalAlignmentBonusInput, {
      min: COMPETITOR_LOCAL_ALIGNMENT_BONUS_MIN,
      max: COMPETITOR_LOCAL_ALIGNMENT_BONUS_MAX,
    });
    if (localAlignmentBonus === null) {
      setCandidateQualityError(
        (
          "Local alignment bonus must be an integer between " +
          `${COMPETITOR_LOCAL_ALIGNMENT_BONUS_MIN} and ${COMPETITOR_LOCAL_ALIGNMENT_BONUS_MAX}.`
        ),
      );
      return;
    }

    setCandidateQualitySubmitting(true);
    try {
      const updated = await updateBusinessSettings(context.token, context.businessId, {
        competitor_candidate_min_relevance_score: minRelevanceScore,
        competitor_candidate_big_box_penalty: bigBoxPenalty,
        competitor_candidate_directory_penalty: directoryPenalty,
        competitor_candidate_local_alignment_bonus: localAlignmentBonus,
      });
      setBusinessSettings(updated);
      setCandidateMinRelevanceScoreInput(String(updated.competitor_candidate_min_relevance_score));
      setCandidateBigBoxPenaltyInput(String(updated.competitor_candidate_big_box_penalty));
      setCandidateDirectoryPenaltyInput(String(updated.competitor_candidate_directory_penalty));
      setCandidateLocalAlignmentBonusInput(String(updated.competitor_candidate_local_alignment_bonus));
      setCandidateQualityMessage("AI competitor candidate quality settings updated.");
    } catch (err) {
      setCandidateQualityError(safeCandidateQualitySettingsUpdateErrorMessage(err));
    } finally {
      setCandidateQualitySubmitting(false);
    }
  };

  const handleSavePromptOverrides = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPromptOverrideMessage(null);
    setPromptOverrideError(null);
    setCrawlPageLimitMessage(null);
    setCandidateQualityMessage(null);

    setPromptOverrideSubmitting(true);
    try {
      const updated = await updateBusinessSettings(context.token, context.businessId, {
        ai_prompt_text_competitor: normalizePromptOverrideInput(competitorPromptOverrideInput),
        ai_prompt_text_recommendations: normalizePromptOverrideInput(recommendationsPromptOverrideInput),
      });
      setBusinessSettings(updated);
      setCompetitorPromptOverrideInput(updated.ai_prompt_text_competitor || "");
      setRecommendationsPromptOverrideInput(updated.ai_prompt_text_recommendations || "");
      setPromptOverrideMessage("AI prompt overrides updated.");
    } catch (err) {
      setPromptOverrideError(safePromptSettingsUpdateErrorMessage(err));
    } finally {
      setPromptOverrideSubmitting(false);
    }
  };

  const handleClearPromptOverrides = async () => {
    setPromptOverrideMessage(null);
    setPromptOverrideError(null);
    setCrawlPageLimitMessage(null);
    setCandidateQualityMessage(null);
    setPromptOverrideSubmitting(true);
    try {
      const updated = await updateBusinessSettings(context.token, context.businessId, {
        ai_prompt_text_competitor: null,
        ai_prompt_text_recommendations: null,
      });
      setBusinessSettings(updated);
      setCompetitorPromptOverrideInput(updated.ai_prompt_text_competitor || "");
      setRecommendationsPromptOverrideInput(updated.ai_prompt_text_recommendations || "");
      setPromptOverrideMessage("AI prompt overrides cleared. Deployment fallback/default is now active.");
    } catch (err) {
      setPromptOverrideError(safePromptSettingsUpdateErrorMessage(err));
    } finally {
      setPromptOverrideSubmitting(false);
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
    return (
      <PageContainer>
        <SectionCard as="div">Loading users...</SectionCard>
      </PageContainer>
    );
  }
  if (context.error) {
    return (
      <PageContainer>
        <SectionCard as="div">Error: {context.error}</SectionCard>
      </PageContainer>
    );
  }
  if (!isAdmin) {
    return (
      <PageContainer>
        <SectionCard>
          <h1>Admin</h1>
          <p className="hint muted">Business administration is available to admin principals only.</p>
        </SectionCard>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <SectionCard>
        <h1>Admin</h1>
        <p>
          Business: <code>{context.businessId}</code>
        </p>
        <div className="link-row">
          <span className="hint muted">Principals: {users.length}</span>
          <span className="hint muted">Active Principals: {activeUsersCount}</span>
          <span className="hint muted">Sign-In Identities: {identities.length}</span>
          <span className="hint muted">Principals Without Identity: {principalsWithoutIdentityCount}</span>
        </div>

        <FormContainer onSubmit={(event) => void handleCreateUser(event)}>
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

          <div className="form-actions">
            <button className="button button-primary" type="submit" disabled={submitting}>
              {submitting ? "Creating..." : "Create User"}
            </button>
          </div>
        </FormContainer>

        <FormContainer onSubmit={(event) => void handleCreateAndLinkIdentity(event)}>
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

          <label htmlFor="identity-email-verified" className="checkbox-chip">
            <input
              id="identity-email-verified"
              type="checkbox"
              checked={identityEmailVerified}
              onChange={(event) => setIdentityEmailVerified(event.target.checked)}
              disabled={identitySubmitting}
            />
            Email verified
          </label>

          <label htmlFor="identity-is-active" className="checkbox-chip">
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

          <div className="form-actions">
            <button
              className="button button-primary"
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
          </div>
        </FormContainer>

        <FormContainer onSubmit={(event) => void handleUpdateCrawlPageLimit(event)} noValidate>
          <h2>SEO Crawl Settings</h2>
          <p className="hint muted">
            Admin-controlled crawl page limit used by SEO audits and automation for this business.
          </p>
          {settingsHealth.crawl.status === "invalid" ? (
            <p className="hint warning">
              Settings health: {settingsHealth.crawl.message}
            </p>
          ) : null}
          <label htmlFor="seo-audit-crawl-max-pages">Crawl Page Limit</label>
          <input
            id="seo-audit-crawl-max-pages"
            type="number"
            min={CRAWL_PAGE_LIMIT_MIN}
            max={CRAWL_PAGE_LIMIT_MAX}
            step={1}
            value={crawlPageLimitInput}
            onChange={(event) => setCrawlPageLimitInput(event.target.value)}
            disabled={businessSettingsLoading || crawlPageLimitSubmitting}
            required
          />
          <p className="hint muted">
            {`Allowed range: ${CRAWL_PAGE_LIMIT_MIN}-${CRAWL_PAGE_LIMIT_MAX}. Current value: `}
            <code>{businessSettings ? String(businessSettings.seo_audit_crawl_max_pages) : String(DEFAULT_CRAWL_PAGE_LIMIT)}</code>.
          </p>
          <div className="form-actions">
            <button
              className="button button-primary"
              type="submit"
              disabled={businessSettingsLoading || crawlPageLimitSubmitting}
            >
              {crawlPageLimitSubmitting ? "Saving..." : "Save Crawl Limit"}
            </button>
          </div>
          {businessSettingsLoading ? <p className="hint muted">Loading business settings...</p> : null}
          {crawlPageLimitMessage ? <p className="hint">{crawlPageLimitMessage}</p> : null}
          {crawlPageLimitError ? <p className="hint error">{crawlPageLimitError}</p> : null}
        </FormContainer>

        <FormContainer onSubmit={(event) => void handleUpdateCompetitorCandidateQuality(event)} noValidate>
          <h2>AI Competitor Candidate Quality</h2>
          <p className="hint muted">
            Admin-controlled deterministic tuning for competitor candidate scoring and exclusion at the business scope.
          </p>
          {settingsHealth.competitorQuality.status === "invalid" ? (
            <p className="hint warning">
              Settings health: {settingsHealth.competitorQuality.message}
            </p>
          ) : null}

          <label htmlFor="competitor-candidate-min-relevance-score">Minimum Relevance Score</label>
          <input
            id="competitor-candidate-min-relevance-score"
            type="number"
            min={COMPETITOR_MIN_RELEVANCE_SCORE_MIN}
            max={COMPETITOR_MIN_RELEVANCE_SCORE_MAX}
            step={1}
            value={candidateMinRelevanceScoreInput}
            onChange={(event) => setCandidateMinRelevanceScoreInput(event.target.value)}
            disabled={businessSettingsLoading || candidateQualitySubmitting}
            required
          />
          <p className="hint muted">
            Controls how closely a competitor must match your business to be included. Higher values mean stricter,
            more relevant matches.
          </p>
          <p className="hint muted">
            Raise this if competitors feel unrelated. Lower it if you are getting too few results.
          </p>

          <label htmlFor="competitor-candidate-big-box-penalty">Big-Box Mismatch Penalty</label>
          <input
            id="competitor-candidate-big-box-penalty"
            type="number"
            min={COMPETITOR_BIG_BOX_PENALTY_MIN}
            max={COMPETITOR_BIG_BOX_PENALTY_MAX}
            step={1}
            value={candidateBigBoxPenaltyInput}
            onChange={(event) => setCandidateBigBoxPenaltyInput(event.target.value)}
            disabled={businessSettingsLoading || candidateQualitySubmitting}
            required
          />
          <p className="hint muted">
            Reduces the chance that large national or big-box companies appear as competitors. Increase this to focus
            more on businesses like yours.
          </p>
          <p className="hint muted">Raise this if large companies dominate your results.</p>

          <label htmlFor="competitor-candidate-directory-penalty">Directory/Aggregator Penalty</label>
          <input
            id="competitor-candidate-directory-penalty"
            type="number"
            min={COMPETITOR_DIRECTORY_PENALTY_MIN}
            max={COMPETITOR_DIRECTORY_PENALTY_MAX}
            step={1}
            value={candidateDirectoryPenaltyInput}
            onChange={(event) => setCandidateDirectoryPenaltyInput(event.target.value)}
            disabled={businessSettingsLoading || candidateQualitySubmitting}
            required
          />
          <p className="hint muted">
            Reduces listings from directories or lead sites (like Yelp, Angi, etc.). Increase this to prioritize real
            business websites instead.
          </p>
          <p className="hint muted">Raise this if you see too many directory or listing sites.</p>

          <label htmlFor="competitor-candidate-local-alignment-bonus">Local Alignment Bonus</label>
          <input
            id="competitor-candidate-local-alignment-bonus"
            type="number"
            min={COMPETITOR_LOCAL_ALIGNMENT_BONUS_MIN}
            max={COMPETITOR_LOCAL_ALIGNMENT_BONUS_MAX}
            step={1}
            value={candidateLocalAlignmentBonusInput}
            onChange={(event) => setCandidateLocalAlignmentBonusInput(event.target.value)}
            disabled={businessSettingsLoading || candidateQualitySubmitting}
            required
          />
          <p className="hint muted">
            Boosts competitors that are located in or serve your area. Increase this to focus more on nearby
            businesses.
          </p>
          <p className="hint muted">Raise this if competitors are not local enough.</p>

          <p className="hint muted">
            Minimum relevance score: {COMPETITOR_MIN_RELEVANCE_SCORE_MIN}-{COMPETITOR_MIN_RELEVANCE_SCORE_MAX}, big-box
            mismatch penalty: {COMPETITOR_BIG_BOX_PENALTY_MIN}-{COMPETITOR_BIG_BOX_PENALTY_MAX}, directory/aggregator
            penalty: {COMPETITOR_DIRECTORY_PENALTY_MIN}-{COMPETITOR_DIRECTORY_PENALTY_MAX}, local alignment bonus:{" "}
            {COMPETITOR_LOCAL_ALIGNMENT_BONUS_MIN}-{COMPETITOR_LOCAL_ALIGNMENT_BONUS_MAX}.
          </p>
          <div className="form-actions">
            <button
              className="button button-primary"
              type="submit"
              disabled={businessSettingsLoading || candidateQualitySubmitting}
            >
              {candidateQualitySubmitting ? "Saving..." : "Save Candidate Quality Settings"}
            </button>
          </div>
          {candidateQualityMessage ? <p className="hint">{candidateQualityMessage}</p> : null}
          {candidateQualityError ? <p className="hint error">{candidateQualityError}</p> : null}
        </FormContainer>

        <FormContainer onSubmit={(event) => void handleSavePromptOverrides(event)} noValidate>
          <h2>AI Prompt Overrides</h2>
          <p className="hint muted">
            Business-level admin prompt overrides for competitor and recommendation generation.
          </p>
          <p className="hint muted">
            Saved values override deployment defaults for this business. Leave blank or clear overrides to use
            deployment fallback/default.
          </p>

          <label htmlFor="ai-prompt-text-competitor">Competitor Prompt</label>
          <textarea
            id="ai-prompt-text-competitor"
            rows={8}
            value={competitorPromptOverrideInput}
            onChange={(event) => setCompetitorPromptOverrideInput(event.target.value)}
            disabled={businessSettingsLoading || promptOverrideSubmitting}
          />
          <p className="hint muted">
            Current source:{" "}
            <strong>
              {businessSettings?.ai_prompt_text_competitor
                ? "Business admin override"
                : "Deployment/default fallback"}
            </strong>
          </p>

          <label htmlFor="ai-prompt-text-recommendations">Recommendations Prompt</label>
          <textarea
            id="ai-prompt-text-recommendations"
            rows={8}
            value={recommendationsPromptOverrideInput}
            onChange={(event) => setRecommendationsPromptOverrideInput(event.target.value)}
            disabled={businessSettingsLoading || promptOverrideSubmitting}
          />
          <p className="hint muted">
            Current source:{" "}
            <strong>
              {businessSettings?.ai_prompt_text_recommendations
                ? "Business admin override"
                : "Deployment/default fallback"}
            </strong>
          </p>

          <div className="form-actions">
            <button
              className="button button-primary"
              type="submit"
              disabled={businessSettingsLoading || promptOverrideSubmitting}
            >
              {promptOverrideSubmitting ? "Saving..." : "Save Prompt Overrides"}
            </button>
            <button
              className="button button-tertiary"
              type="button"
              onClick={() => void handleClearPromptOverrides()}
              disabled={businessSettingsLoading || promptOverrideSubmitting}
            >
              Use Deployment Fallbacks
            </button>
          </div>
          {promptOverrideMessage ? <p className="hint">{promptOverrideMessage}</p> : null}
          {promptOverrideError ? <p className="hint error">{promptOverrideError}</p> : null}
        </FormContainer>

        <div className="message-stack">
          {submitSuccess ? <p className="hint">{submitSuccess}</p> : null}
          {submitError ? <p className="hint error">{submitError}</p> : null}
          {identitySubmitSuccess ? <p className="hint">{identitySubmitSuccess}</p> : null}
          {identitySubmitError ? <p className="hint error">{identitySubmitError}</p> : null}
          {actionSuccess ? <p className="hint">Principal action: {actionSuccess}</p> : null}
          {actionError ? <p className="hint error">Principal action: {actionError}</p> : null}
          {identityActionSuccess ? <p className="hint">Identity action: {identityActionSuccess}</p> : null}
          {identityActionError ? <p className="hint error">Identity action: {identityActionError}</p> : null}
          {businessSettingsLoadError ? <p className="hint error">{businessSettingsLoadError}</p> : null}
          {settingsHealth.notifications.status === "invalid" ? (
            <p className="hint warning">
              Notification settings health: {settingsHealth.notifications.message}
            </p>
          ) : null}
          {loadingUsers ? <p className="hint muted">Loading users...</p> : null}
          {usersError ? <p className="hint error">{usersError}</p> : null}
          {identityWarning ? <p className="hint warning">{identityWarning}</p> : null}
          {!loadingUsers && users.length > 0 && principalsWithoutIdentityCount > 0 ? (
            <p className="hint muted">
              Some principals have no mapped sign-in identity yet. They will not be able to authenticate until an identity is linked.
            </p>
          ) : null}
        </div>
      </SectionCard>

      <SectionCard>
        <h2>Principals and Identities</h2>
        <div className="table-container">
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
                    <td className="table-cell-wrap">{user.id}</td>
                    <td className="table-cell-wrap">{user.display_name}</td>
                    <td>{user.role}</td>
                    <td>{user.is_active ? "yes" : "no"}</td>
                    <td>{user.last_authenticated_at || "never"}</td>
                    <td>
                      {userIdentities.length === 0 ? (
                        "none"
                      ) : (
                        <ul className="compact-list">
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
                        <div className="button-stack">
                          {userIdentities.map((identity) => (
                            <button
                              key={identity.id}
                              type="button"
                              className={
                                identity.is_active
                                  ? "button button-danger button-inline"
                                  : "button button-secondary button-inline"
                              }
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
                        className={
                          user.is_active
                            ? "button button-danger button-inline"
                            : "button button-secondary button-inline"
                        }
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
        </div>
      </SectionCard>
    </PageContainer>
  );
}
