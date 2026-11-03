// 프로필 API(규약 4.1). 음성 대화는 서버가 내려주는 읽기 전용 client 설정값(VAD 임계값 등)을 쓴다.
import { request } from './http.ts'
import type { components } from './schema.d.ts'

export type Profile = components['schemas']['ProfileResponse']
export type ClientConfig = components['schemas']['ClientConfig']

export async function getProfile(signal?: AbortSignal): Promise<Profile> {
  return (await request('/api/profile', 'GET', undefined, signal)).json()
}

export type ProfilePatch = components['schemas']['ProfileUpdate']

/** PUT /api/profile: 보낸 필드만 바꾸고 바뀐 전체 프로필을 돌려준다(규약 4.1). 검증 오류는 ApiError(422) */
export async function updateProfile(patch: ProfilePatch, signal?: AbortSignal): Promise<Profile> {
  return (await request('/api/profile', 'PUT', patch, signal)).json()
}
