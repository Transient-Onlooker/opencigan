export async function apiError(response: Response): Promise<Error> {
  const body = await response.json().catch(() => null) as { code?: unknown } | null;
  const code = typeof body?.code === 'string' ? body.code : '';
  let message = `요청을 완료하지 못했어요. (${response.status})`;
  if (response.status === 429) {
    message = '요청이 너무 많아요. 잠시 후 다시 시도해 주세요.';
  } else if (response.status === 502) {
    message = '서버 간 연결에 문제가 생겼어요. 잠시 후 다시 시도해 주세요.';
  } else if (response.status === 504) {
    message = '서버 응답이 늦어요. 잠시 후 다시 시도해 주세요.';
  } else if (response.status === 503) {
    if (code === 'history_disabled') message = '이 학교는 변경 이력을 제공하지 않습니다.';
    else if (code === 'service_overloaded') message = '서버에 요청이 몰리고 있어요. 잠시 후 다시 시도해 주세요.';
    else if (code === 'upstream_unavailable') message = '시간표나 급식 데이터를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.';
    else if (code === 'gateway_unavailable' || code === 'gateway_unconfigured') message = 'API 서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.';
    else message = '서비스를 일시적으로 이용할 수 없어요. 잠시 후 다시 시도해 주세요.';
  }
  if ([429, 502, 503, 504].includes(response.status)) {
    const retryAfter = response.headers.get('Retry-After');
    if (retryAfter && /^\d{1,5}$/.test(retryAfter)) {
      const seconds = Number(retryAfter);
      if (seconds > 0 && seconds <= 86400) message = message.replace('잠시 후', `${seconds}초 후`);
    }
  }
  return Object.assign(new Error(message), { code });
}
