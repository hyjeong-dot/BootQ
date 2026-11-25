// 우측 하단 토스트 (SCR-001). 카드 1~3장을 한 장씩 보여주고, 카드마다 👍/👎를 따로 받는다
import { sendFeedback } from './api.js';
import type { Card, DownReason, Vote } from './types.js';

const DOWN_REASONS: ReadonlyArray<readonly [DownReason, string]> = [
  ['job_mismatch', '직무가 달라요'],
  ['industry_mismatch', '분야가 달라요'],
  ['not_needed', '지금 필요한 도움이 아니에요'],
  ['other', '기타'],
];

type FeedbackState = 'idle' | 'choosing' | 'sending' | 'done' | 'failed';

interface ToastState {
  recId: string;
  cards: Card[];
  feedback: FeedbackState[];
  idx: number;
}

let state: ToastState | null = null;

function el<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`#${id} 없음`);
  return node as T;
}

function button(label: string, className: string, onClick: () => void, ariaLabel?: string): HTMLButtonElement {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = className;
  b.textContent = label;
  if (ariaLabel) b.setAttribute('aria-label', ariaLabel);
  b.addEventListener('click', onClick);
  return b;
}

/** 👍/👎 아이콘 버튼 (목업 아이콘을 그대로 쓰려고 index.html의 template을 복제) */
function iconButton(templateId: string, onClick: () => void): HTMLButtonElement {
  const tpl = el<HTMLTemplateElement>(templateId);
  const b = tpl.content.firstElementChild!.cloneNode(true) as HTMLButtonElement;
  b.addEventListener('click', onClick);
  return b;
}

function renderFeedback(s: ToastState): void {
  const box = el('fb');
  box.replaceChildren();
  const fb = s.feedback[s.idx] ?? 'idle';
  const ask = document.createElement('span');
  ask.className = 'ask';
  box.append(ask);

  switch (fb) {
    case 'idle':
    case 'failed':
      ask.textContent = fb === 'failed' ? '전송하지 못했어요. 다시 눌러 주세요' : '이 추천이 도움이 됐나요?';
      box.append(
        iconButton('tpl-up', () => vote('up')),
        iconButton('tpl-down', () => { setFeedback(s, s.idx, 'choosing'); }),
      );
      break;
    case 'choosing': {
      box.classList.add('choosing');
      ask.textContent = '어떤 점이 아쉬웠나요?';
      const chips = document.createElement('div');
      chips.className = 'reasons';
      for (const [code, label] of DOWN_REASONS) {
        chips.append(button(label, 'chip', () => vote('down', code)));
      }
      chips.append(button('취소', 'chip chip-ghost', () => { setFeedback(s, s.idx, 'idle'); }));
      box.append(chips);
      break;
    }
    case 'sending':
      ask.textContent = '보내는 중…';
      break;
    case 'done':
      ask.textContent = '피드백 감사합니다.';
      break;
  }
  if (fb !== 'choosing') box.classList.remove('choosing');
}

/** `YYYY-MM-DD` → `MM.DD` */
function mmdd(iso: string): string {
  const [, m, d] = iso.split('-');
  return `${m}.${d}`;
}

/** 오늘(브라우저 시간)부터 마감일까지 남은 날 */
function dDay(endIso: string): string {
  const [y, m, d] = endIso.split('-').map(Number);
  const end = new Date(y ?? 0, (m ?? 1) - 1, d ?? 1);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((end.getTime() - today.getTime()) / 86_400_000);
  return days === 0 ? 'D-DAY' : `D-${days}`;
}

/** 목업 형식 "09.01 ~ 10.31 · D-30". 기간 데이터가 없으면 자리 문구 */
function periodText(c: Card): string {
  if (!c.recruit_start && !c.recruit_end) return '모집기간 정보 없음';
  const range = `${c.recruit_start ? mmdd(c.recruit_start) : ''} ~ ${c.recruit_end ? mmdd(c.recruit_end) : ''}`.trim();
  return c.recruit_end ? `${range} · ${dDay(c.recruit_end)}` : range;
}

function renderMeta(c: Card): void {
  const tags = el('tags');
  tags.replaceChildren(...c.tags.map((t) => {
    const s = document.createElement('span');
    s.textContent = `#${t}`;
    return s;
  }));
  const period = el('period');
  period.textContent = periodText(c);
  period.classList.toggle('is-empty', !c.recruit_start && !c.recruit_end);
}

function render(): void {
  const s = state;
  if (!s) return;
  const card = s.cards[s.idx];
  if (!card) return;
  const many = s.cards.length > 1;
  el('prev').hidden = !many;
  el('next').hidden = !many;
  el('pager').hidden = !many;
  el('pager').textContent = `${s.idx + 1} / ${s.cards.length}`;
  el('notice').hidden = !card.review;
  el('camp-name').textContent = card.camp_name;
  el('camp-reason').textContent = card.reason;
  renderMeta(card);
  renderFeedback(s);
}

function setFeedback(s: ToastState, idx: number, fb: FeedbackState): void {
  s.feedback[idx] = fb;
  if (state === s) render();
}

function vote(v: Vote, reason?: DownReason): void {
  const s = state;
  if (!s) return;
  const idx = s.idx;
  const card = s.cards[idx];
  if (!card) return;
  setFeedback(s, idx, 'sending');
  const body = reason ? { rank: card.rank, camp_id: card.camp_id, vote: v, reason } : { rank: card.rank, camp_id: card.camp_id, vote: v };
  sendFeedback(s.recId, body).then(
    () => setFeedback(s, idx, 'done'),
    () => setFeedback(s, idx, 'failed'),
  );
}

function move(step: number): void {
  const s = state;
  if (!s) return;
  const n = s.cards.length;
  s.idx = (s.idx + step + n) % n;
  render();
}

/** 카드가 1장 이상일 때만 부른다 (0장이면 토스트를 띄우지 않는다) */
export function showToast(recId: string, cards: Card[]): void {
  const sorted = [...cards].sort((a, b) => a.rank - b.rank);
  state = { recId, cards: sorted, feedback: sorted.map(() => 'idle'), idx: 0 };
  render();
  const toast = el('toast');
  toast.hidden = false;
  // 다음 프레임에 클래스를 빼야 아래에서 올라오는 전환이 보인다
  requestAnimationFrame(() => requestAnimationFrame(() => toast.classList.remove('is-closed')));
}

export function hideToast(): void {
  state = null;
  const toast = el('toast');
  toast.classList.add('is-closed');
}

export function initToast(): void {
  el('prev').addEventListener('click', () => move(-1));
  el('next').addEventListener('click', () => move(1));
  el('close').addEventListener('click', hideToast);
  const toast = el('toast');
  // 내려가는 전환이 끝나면 접근성 트리에서도 뺀다
  toast.addEventListener('transitionend', () => {
    if (toast.classList.contains('is-closed')) toast.hidden = true;
  });
}
