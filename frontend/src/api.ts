// 글 등록(API-001), SSE(API-002), 피드백(API-003). 같은 출처라 상대 경로만 쓴다
import type {
  ApiErrorBody, FeedbackCreated, FeedbackIn, PostCreated, PostIn, RecommendationEvent, TimeoutEvent,
} from './types.js';

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message);
  }
}

function isErrorBody(x: unknown): x is ApiErrorBody {
  if (typeof x !== 'object' || x === null || !('error' in x)) return false;
  const e = (x as { error: unknown }).error;
  return typeof e === 'object' && e !== null && 'code' in e && 'message' in e;
}

/** POST JSON 공통 함수. 에러 규약 `{"error": {"code", "message"}}`만 해석한다 */
async function postJson<T>(url: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, 'network_error', '서버에 연결하지 못했어요');
  }
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    if (isErrorBody(data)) throw new ApiError(res.status, data.error.code, data.error.message);
    throw new ApiError(res.status, 'unknown_error', `요청 실패 (HTTP ${res.status})`);
  }
  return data as T;
}

export function createPost(post: PostIn): Promise<PostCreated> {
  return postJson<PostCreated>('/api/posts', post);
}

export function sendFeedback(recId: string, fb: FeedbackIn): Promise<FeedbackCreated> {
  return postJson<FeedbackCreated>(`/api/recommendations/${encodeURIComponent(recId)}/feedback`, fb);
}

export interface StreamHandlers {
  onResult(ev: RecommendationEvent): void;
  onTimeout(ev: TimeoutEvent): void;
  /** 이벤트를 받기 전에 연결이 끊김 (EventSource는 HTTP 상태 코드를 알려주지 않는다) */
  onError(): void;
}

/**
 * 추천 결과 SSE에 연결한다. 이벤트는 하나만 오고 서버가 닫는다.
 * 서버가 닫으면 EventSource가 자동 재접속하므로, 이벤트를 받는 즉시 직접 close()한다.
 * 반환값은 연결을 끊는 함수 (새 글을 등록할 때 이전 연결 정리용)
 */
export function streamRecommendation(postId: string, h: StreamHandlers): () => void {
  const es = new EventSource(`/api/posts/${encodeURIComponent(postId)}/recommendations/stream`);
  let settled = false;
  const finish = (): boolean => {
    if (settled) return false;
    settled = true;
    es.close();
    return true;
  };
  es.addEventListener('recommendation', (e: MessageEvent<string>) => {
    if (finish()) h.onResult(JSON.parse(e.data) as RecommendationEvent);
  });
  es.addEventListener('timeout', (e: MessageEvent<string>) => {
    if (finish()) h.onTimeout(JSON.parse(e.data) as TimeoutEvent);
  });
  es.onerror = () => {
    if (finish()) h.onError();
  };
  return () => { settled = true; es.close(); };
}
