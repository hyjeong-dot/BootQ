// 진입점 (SCR-001): 예시 글 채우기 → 글 등록(API-001) → SSE(API-002) → 토스트
import { ApiError, createPost, streamRecommendation } from './api.js';
import { hideToast, initToast, showToast } from './toast.js';
import type { PostIn } from './types.js';

/** 데모용 예시 글. 모두 지어낸 문장이다 (실제 유저 글을 쓰지 않는다) */
const EXAMPLES: ReadonlyArray<{ label: string; post: PostIn }> = [
  {
    label: '마케팅 신입',
    post: {
      category_group: '취업 고민', category: '직무', target_job: '모든 직무', target_company: '모든 회사',
      title: '마케팅 신입으로 가려면 어떤 경험을 쌓아야 할까요',
      content: '경영학과 4학년입니다. 브랜드 마케팅 직무에 관심이 있는데 관련 인턴 경험이 없어요. '
        + '졸업 전에 실무를 미리 경험해 볼 방법이 있을까요?',
    },
  },
  {
    label: '반도체 공정',
    post: {
      category_group: '취업 고민', category: '직무', target_job: '모든 직무', target_company: '삼성전자',
      title: '반도체 공정기술 직무 준비 방향이 궁금해요',
      content: '신소재공학 전공입니다. 반도체 공정기술 엔지니어를 희망하는데 학부 실습 말고는 공정 경험이 없습니다. '
        + '어떤 준비가 도움이 될까요?',
    },
  },
  {
    label: '2차전지 품질 자소서',
    post: {
      category_group: '취업 고민', category: '자소서', target_job: '품질관리', target_company: '모든 회사',
      title: '배터리 회사 품질 직무 자소서가 막막합니다',
      content: '2차전지 기업 품질관리 직무에 지원하려고 해요. 관련 경험이 짧은 프로젝트 하나뿐인데 '
        + '자기소개서에 직무 역량을 어떻게 보여줘야 할지 모르겠습니다.',
    },
  },
  {
    label: '필드와 본문이 다름',
    post: {
      category_group: '취업 고민', category: '스펙', target_job: '데이터분석가', target_company: '모든 회사',
      title: '데이터 쪽으로 가고 싶은데 스펙이 부족해요',
      content: '통계학과 졸업 예정입니다. 처음엔 데이터 분석을 생각했는데 요즘은 서비스 기획에도 관심이 생겼어요. '
        + 'SQL은 기초만 할 줄 압니다. 어느 쪽이든 실무 경험을 쌓고 싶어요.',
    },
  },
  {
    label: '추천 없음 (랜선 사수)',
    post: {
      category_group: '랜선 사수', category: '직장생활', target_job: '모든 직무', target_company: '모든 회사',
      title: '팀장님께 보고할 때 자꾸 말이 길어져요',
      content: '입사 1년 차입니다. 주간 보고 때마다 핵심만 말하라는 피드백을 받는데 어떻게 연습하면 좋을까요?',
    },
  },
];

const FIELDS = ['category_group', 'category', 'target_job', 'target_company', 'title', 'content'] as const;

function el<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`#${id} 없음`);
  return node as T;
}

type Field = HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;
const field = (name: (typeof FIELDS)[number]): Field => el<Field>(`f-${name}`);

function readForm(): PostIn {
  return {
    title: field('title').value,
    content: field('content').value,
    category: field('category').value,
    category_group: field('category_group').value,
    target_job: field('target_job').value.trim(),
    target_company: field('target_company').value.trim(),
  };
}

function fillForm(p: PostIn): void {
  for (const name of FIELDS) field(name).value = p[name];
}

// ---- 상태 줄 (데모 보조. 토스트 규칙과 별개) ----

type Tone = 'info' | 'ok' | 'muted' | 'warn';

function setStatus(text: string, tone: Tone, retry?: () => void): void {
  const box = el('status');
  box.dataset['tone'] = tone;
  box.replaceChildren(document.createTextNode(text));
  if (retry) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'link-btn';
    b.textContent = '다시 받기';
    b.addEventListener('click', retry);
    box.append(' ', b);
  }
}

// ---- 등록 → SSE ----

let stopStream: (() => void) | null = null;
let busy = false;

function setBusy(on: boolean): void {
  busy = on;
  el<HTMLButtonElement>('submit').disabled = on;
}

function listen(postId: string, startedAt: number): void {
  stopStream?.();
  setBusy(true);
  setStatus('추천을 찾고 있어요…', 'info');
  const retry = () => listen(postId, startedAt);
  stopStream = streamRecommendation(postId, {
    onResult(ev) {
      stopStream = null;
      setBusy(false);
      const sec = ((performance.now() - startedAt) / 1000).toFixed(1);
      if (ev.cards.length === 0) {
        setStatus(`추천할 캠프가 없어 토스트를 띄우지 않았어요 (${sec}초)`, 'muted');
        return;
      }
      setStatus(`추천 ${ev.cards.length}개를 받았어요 (${sec}초)`, 'ok');
      showToast(ev.recommendation_id, ev.cards);
    },
    onTimeout() {
      stopStream = null;
      setBusy(false);
      setStatus('응답이 늦어요. 처리는 계속되고 있어요.', 'warn', retry);
    },
    onError() {
      stopStream = null;
      setBusy(false);
      setStatus('추천 결과를 받지 못했어요.', 'warn', retry);
    },
  });
}

async function submit(e: SubmitEvent): Promise<void> {
  e.preventDefault();
  if (busy) return;
  stopStream?.();
  stopStream = null;
  hideToast();
  setBusy(true);
  setStatus('글을 등록하고 있어요…', 'info');
  const startedAt = performance.now();
  try {
    const created = await createPost(readForm());
    listen(created.post_id, startedAt);
  } catch (err) {
    setBusy(false);
    setStatus(err instanceof ApiError ? err.message : '글을 등록하지 못했어요.', 'warn');
  }
}

function init(): void {
  initToast();
  const box = el('examples');
  for (const ex of EXAMPLES) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip';
    b.textContent = ex.label;
    b.addEventListener('click', () => fillForm(ex.post));
    box.append(b);
  }
  el<HTMLFormElement>('post-form').addEventListener('submit', (e) => { void submit(e); });
}

init();
