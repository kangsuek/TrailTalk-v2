// 자동 생성 파일(npm run gen:api). 직접 고치지 않는다.

export interface paths {
    "/api/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health */
        get: operations["health_api_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Profile */
        get: operations["get_profile_api_profile_get"];
        /** Put Profile */
        put: operations["put_profile_api_profile_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sessions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Session */
        post: operations["create_session_api_sessions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sessions/{session_id}/turns": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Turn */
        post: operations["create_turn_api_sessions__session_id__turns_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sessions/{session_id}/end": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * End Session
         * @description 세션을 끝내고 마무리 멘트를 준다(멱등). 일지 정리(추출)는 M2에서 더한다.
         */
        post: operations["end_session_api_sessions__session_id__end_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AckOut */
        AckOut: {
            /** Text */
            text: string;
            /** Audio */
            audio: string | null;
        };
        /** AudioConfig */
        AudioConfig: {
            upload: components["schemas"]["UploadAudioConfig"];
            response: components["schemas"]["ResponseAudioConfig"];
        };
        /**
         * ChatModel
         * @enum {string}
         */
        ChatModel: "haiku" | "sonnet" | "opus";
        /** ClientConfig */
        ClientConfig: {
            vad: components["schemas"]["VadConfig"];
            session: components["schemas"]["ClientSessionConfig"];
            audio: components["schemas"]["AudioConfig"];
            turn: components["schemas"]["TurnConfig"];
        };
        /** ClientSessionConfig */
        ClientSessionConfig: {
            /** Idle Timeout Minutes */
            idle_timeout_minutes: number;
        };
        /** GreetingOut */
        GreetingOut: {
            /** Turn Id */
            turn_id: string;
            /** Text */
            text: string;
            /** Audio */
            audio: string | null;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HealthResponse */
        HealthResponse: {
            /**
             * Status
             * @constant
             */
            status: "ok";
            /**
             * Db
             * @constant
             */
            db: "ok";
        };
        /**
         * PersonaOut
         * @description 화면에 보일 캐릭터 정보. 클라이언트는 캐릭터 이름을 코드에 두지 않고 이 값을 쓴다(NFR-08).
         */
        PersonaOut: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Ack */
            ack: components["schemas"]["AckOut"][];
        };
        /** ProfileResponse */
        ProfileResponse: {
            /** Nickname */
            nickname: string | null;
            /** Email */
            email: string | null;
            /** Mail Ready */
            mail_ready: boolean;
            /** Interests */
            interests: string[];
            /** Persona Id */
            persona_id: string;
            /** Voice */
            voice: string | null;
            /** Speaking Rate */
            speaking_rate: number | null;
            /** Ack Enabled */
            ack_enabled: boolean;
            /** Keep Audio */
            keep_audio: boolean;
            chat_model: components["schemas"]["ChatModel"] | null;
            default_chat_model: components["schemas"]["ChatModel"];
            client: components["schemas"]["ClientConfig"];
        };
        /**
         * ProfileUpdate
         * @description 보낸 필드만 바꾼다. 읽기 전용 필드(client 등)를 보내면 422다.
         */
        ProfileUpdate: {
            /** Nickname */
            nickname?: string | null;
            /** Email */
            email?: string | null;
            /** Interests */
            interests?: string[] | null;
            /** Persona Id */
            persona_id?: string | null;
            /** Voice */
            voice?: string | null;
            /** Speaking Rate */
            speaking_rate?: number | null;
            /** Ack Enabled */
            ack_enabled?: boolean | null;
            /** Keep Audio */
            keep_audio?: boolean | null;
            chat_model?: components["schemas"]["ChatModel"] | null;
        };
        /** ResponseAudioConfig */
        ResponseAudioConfig: {
            /**
             * Codec
             * @constant
             */
            codec: "mp3";
        };
        /** SavedCounts */
        SavedCounts: {
            /** Idea */
            idea: number;
            /** Todo */
            todo: number;
            /** Memo */
            memo: number;
        };
        /**
         * SessionClosed
         * @description 끝내기 응답. closing은 캐릭터가 하는 마무리 멘트, saved는 이 대화에서 저장한 노트 개수다.
         *
         *     journal_status는 일지 정리(M2) 전까지 항상 null이다.
         */
        SessionClosed: {
            session: components["schemas"]["SessionOut"];
            /** Closing */
            closing: string;
            /** Closing Audio */
            closing_audio: string | null;
            saved: components["schemas"]["SavedCounts"];
            /** Journal Status */
            journal_status: ("pending" | "done" | "failed") | null;
        };
        /** SessionCreate */
        SessionCreate: {
            /**
             * Mode
             * @default text
             * @enum {string}
             */
            mode: "text" | "voice";
        };
        /** SessionOut */
        SessionOut: {
            /** Id */
            id: string;
            /**
             * Mode
             * @enum {string}
             */
            mode: "text" | "voice";
            /**
             * Status
             * @enum {string}
             */
            status: "active" | "paused" | "ended";
            /**
             * Started At
             * Format: date-time
             */
            started_at: string;
            /** Ended At */
            ended_at: string | null;
        };
        /** SessionStarted */
        SessionStarted: {
            session: components["schemas"]["SessionOut"];
            greeting: components["schemas"]["GreetingOut"];
            persona: components["schemas"]["PersonaOut"];
        };
        /**
         * TurnConfig
         * @description 맞장구(규약 6.4)와 쪼개진 발화 병합(2.8) 기준.
         */
        TurnConfig: {
            /** Ack Delay Ms */
            ack_delay_ms: number;
            /** Ack Min Speech Ms */
            ack_min_speech_ms: number;
            /** Ack Overlap Max Ms */
            ack_overlap_max_ms: number;
            /** Merge Min Speech Ms */
            merge_min_speech_ms: number;
        };
        /** TurnCreate */
        TurnCreate: {
            /** Text */
            text: string;
        };
        /** UploadAudioConfig */
        UploadAudioConfig: {
            /**
             * Codec
             * @constant
             */
            codec: "opus";
            /**
             * Sample Rate Hz
             * @constant
             */
            sample_rate_hz: 16000;
            /**
             * Channels
             * @constant
             */
            channels: 1;
        };
        /**
         * VadConfig
         * @description Silero VAD 확률 임계값과 발화 길이. 재생 중(setVadMode playback)에는 playback_* 값을 쓴다.
         */
        VadConfig: {
            /** Speech Threshold */
            speech_threshold: number;
            /** Silence Threshold */
            silence_threshold: number;
            /** Playback Speech Threshold */
            playback_speech_threshold: number;
            /** Playback Silence Threshold */
            playback_silence_threshold: number;
            /** End Of Speech Silence Ms */
            end_of_speech_silence_ms: number;
            /** Min Speech Ms */
            min_speech_ms: number;
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
        /**
         * DoneEvent
         * @description 턴 끝. session_status가 paused/ended면 도구(pause_session/end_session)가 바꾼 것이다.
         */
        DoneEvent: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "done";
            /** Turn Id */
            turn_id: string;
            /** Text */
            text: string;
            /**
             * Interrupted
             * @default false
             */
            interrupted: boolean;
            /**
             * Session Status
             * @default active
             * @enum {string}
             */
            session_status: "active" | "paused" | "ended";
            /**
             * Superseded
             * @default false
             */
            superseded: boolean;
        };
        /**
         * ErrorEvent
         * @description 스트림 도중 오류. code는 공통 오류 형식(client-contract 9절)과 같은 값이다.
         */
        ErrorEvent: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "error";
            /** Code */
            code: string;
            /** Message */
            message: string;
        };
        /**
         * SentenceEvent
         * @description 캐릭터 답변의 한 문장. index는 턴 안에서 0부터 증가한다.
         *
         *     audio·speech_text는 음성 세션(M3)에서만 값이 오고 글 대화에서는 항상 null이다.
         */
        SentenceEvent: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "sentence";
            /** Index */
            index: number;
            /** Text */
            text: string;
            /**
             * Audio
             * @default null
             */
            audio: string | null;
            /**
             * Speech Text
             * @default null
             */
            speech_text: string | null;
        };
        /**
         * ToolEvent
         * @description 도구 사용. start(이름만) → call(입력 완성) → end(결과 요약) 순서로 온다.
         */
        ToolEvent: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "tool";
            /**
             * Phase
             * @enum {string}
             */
            phase: "start" | "call" | "end";
            /** Tool Use Id */
            tool_use_id: string;
            /** Name */
            name: string;
            /**
             * Input
             * @default null
             */
            input: {
                [key: string]: unknown;
            } | null;
            /**
             * Summary
             * @default null
             */
            summary: components["schemas"]["ToolResultSummary"] | null;
            /**
             * Is Error
             * @default false
             */
            is_error: boolean;
            /** @default null */
            notice: components["schemas"]["VoiceNotice"] | null;
        };
        /**
         * ToolResultSummary
         * @description 앱 도구(save_note 등) 결과. result는 도구가 돌려준 값(보통 문자열).
         */
        ToolResultSummary: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "result";
            /** Result */
            result: unknown;
        };
        /**
         * TurnEvent
         * @description 스트림의 첫 이벤트. turn_id는 이번 답변(assistant 턴)의 ID로 끼어들기(M4)에 쓴다.
         */
        TurnEvent: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "turn";
            /** Turn Id */
            turn_id: string;
        };
        /**
         * VoiceNotice
         * @description 답변이 아닌 안내 음성(예: 검색 전 "잠깐 찾아볼게요", M3). audio는 MP3(base64) 또는 null.
         */
        VoiceNotice: {
            /** Text */
            text: string;
            /** Audio */
            audio: string | null;
        };
        StreamEvent: components["schemas"]["TurnEvent"] | components["schemas"]["SentenceEvent"] | components["schemas"]["ToolEvent"] | components["schemas"]["DoneEvent"] | components["schemas"]["ErrorEvent"];
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    health_api_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
        };
    };
    get_profile_api_profile_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProfileResponse"];
                };
            };
        };
    };
    put_profile_api_profile_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProfileUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProfileResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_session_api_sessions_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SessionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionStarted"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_turn_api_sessions__session_id__turns_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TurnCreate"];
            };
        };
        responses: {
            /** @description 턴 이벤트 스트림(turn → sentence·tool → done 또는 error) */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/event-stream": components["schemas"]["StreamEvent"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    end_session_api_sessions__session_id__end_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionClosed"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
