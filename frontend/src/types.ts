// API 응답 타입 (docs/specs/10_API_SPEC.md). 수동 정의 — API가 바뀌면 같은 작업에서 갱신한다 (03_FRONTEND.md 4장)

/** API-001 요청 */
export interface PostIn {
  title: string;
  content: string;
  category: string;
  category_group: string;
  target_job: string;
  target_company: string;
}

/** API-001 응답 (201) */
export interface PostCreated {
  post_id: string;
  recommendation_id: string;
  status: 'processing';
}

/** API-002 카드 */
export interface Card {
  rank: number;
  camp_id: string;
  camp_name: string;
  reason: string;
  /** 리뷰 플래그 (B등급·산업만 매칭) → 안내 문구 */
  review: boolean;
  /** 표시용 해시태그 (`#` 없이) 0~4개 */
  tags: string[];
  /** 모집기간 `YYYY-MM-DD`. 데이터가 없으면 null */
  recruit_start: string | null;
  recruit_end: string | null;
}

/** API-002 `event: recommendation` */
export interface RecommendationEvent {
  recommendation_id: string;
  status: 'done' | 'failed';
  /** 0~3장. 비어 있으면 토스트를 띄우지 않는다 */
  cards: Card[];
}

/** API-002 `event: timeout` */
export interface TimeoutEvent {
  recommendation_id: string;
}

export type Vote = 'up' | 'down';
export type DownReason = 'job_mismatch' | 'industry_mismatch' | 'not_needed' | 'other';

/** API-003 요청 */
export interface FeedbackIn {
  rank: number;
  camp_id: string;
  vote: Vote;
  reason?: DownReason;
}

/** API-003 응답 (201) */
export interface FeedbackCreated {
  feedback_id: string;
}

/** 에러 규약 (02_BACKEND.md 2장) */
export interface ApiErrorBody {
  error: { code: string; message: string };
}
