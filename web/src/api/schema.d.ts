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
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
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
}
