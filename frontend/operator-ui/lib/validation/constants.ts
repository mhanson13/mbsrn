// Contract guardrail:
// These bounds must remain aligned with backend validation constants in
// app/services/business_settings.py.
export const CRAWL_PAGE_LIMIT_MIN = 5;
export const CRAWL_PAGE_LIMIT_MAX = 250;
export const DEFAULT_CRAWL_PAGE_LIMIT = 25;

export const COMPETITOR_MIN_RELEVANCE_SCORE_MIN = 0;
export const COMPETITOR_MIN_RELEVANCE_SCORE_MAX = 100;
export const COMPETITOR_BIG_BOX_PENALTY_MIN = 0;
export const COMPETITOR_BIG_BOX_PENALTY_MAX = 50;
export const COMPETITOR_DIRECTORY_PENALTY_MIN = 0;
export const COMPETITOR_DIRECTORY_PENALTY_MAX = 50;
export const COMPETITOR_LOCAL_ALIGNMENT_BONUS_MIN = 0;
export const COMPETITOR_LOCAL_ALIGNMENT_BONUS_MAX = 50;
export const COMPETITOR_TIMEOUT_SECONDS_MIN = 10;
export const COMPETITOR_TIMEOUT_SECONDS_MAX = 90;
export const DEFAULT_COMPETITOR_TIMEOUT_SECONDS = 30;

export const NOTIFICATION_PHONE_E164_REGEX = /^\+[1-9]\d{9,14}$/;
export const NOTIFICATION_EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
