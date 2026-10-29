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
    "/api/sessions/{session_id}/reopen": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Reopen Session
         * @description 끝난 대화(또는 열려 있지 않은 진행 중 대화)를 같은 세션으로 다시 열어 이어서 대화한다.
         *     답변 중이면 409 turn_in_progress, 재개 인사말을 받지 못하면 시작 실패와 같은 오류이고 대화는
         *     원래 상태로 남는다.
         */
        post: operations["reopen_session_api_sessions__session_id__reopen_post"];
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
    "/api/sessions/{session_id}/turns/audio": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Audio Turn
         * @description 말 한 번의 오디오 바이트(multipart 아님)를 인식해 턴을 시작한다. SSE를 열기 전에 인식하므로
         *     오디오·인식 오류와 말 없음은 JSON 오류이고 사용자 메시지를 만들지 않는다.
         */
        post: operations["create_audio_turn_api_sessions__session_id__turns_audio_post"];
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
         * @description 세션을 끝내고 일지 정리를 띄워 최대 extract_wait_s 기다린 뒤 마무리 멘트를 준다(멱등).
         *     마무리 멘트의 저장 개수는 정리로 더해진 노트까지 센다.
         */
        post: operations["end_session_api_sessions__session_id__end_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/journal": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Journal
         * @description 현지 날짜 범위(from~to, 둘 다 포함)의 일지. 기본은 최근 30일. 최신순.
         *
         *     사용자가 한마디도 하지 않은 대화(인사말만 있는 것)는 빼고 준다. 진행 중인 대화는 나온다.
         */
        get: operations["list_journal_api_journal_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/journal/{session_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Journal
         * @description 일지 상세. 목록에서 빠지는 대화(사용자 발화 없음)도 ID로는 조회된다.
         */
        get: operations["get_journal_api_journal__session_id__get"];
        put?: never;
        post?: never;
        /**
         * Delete Journal
         * @description 대화를 지운다(전문·노트까지). 진행 중인 대화는 409 session_active, 답변을 만드는 중이면
         *     409 turn_in_progress. 쉬는 중이면 CLI를 정리하고, 돌던 일지 정리는 멈춘다.
         */
        delete: operations["delete_journal_api_journal__session_id__delete"];
        options?: never;
        head?: never;
        /**
         * Update Journal
         * @description 대화 제목을 고친다. 고친 제목은 일지를 다시 정리해도 바뀌지 않는다.
         */
        patch: operations["update_journal_api_journal__session_id__patch"];
        trace?: never;
    };
    "/api/journal/{session_id}/retry": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Retry Journal
         * @description 정리에 실패한(또는 정리 기록이 없는) 끝난 대화, 예전 형식으로 정리된 대화를 다시 정리한다.
         *     정리 중이거나 새 형식으로 정리를 마쳤으면 그대로 둔다.
         *
         *     정리는 백그라운드로 돈다. 응답의 journal_status가 pending이면 상세를 다시 불러와 끝을 본다.
         */
        post: operations["retry_journal_api_journal__session_id__retry_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/notes/open-ideas": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Open Ideas
         * @description 시작 화면의 "지난 아이디어 이어 가기" 목록. 완료하지 않은 아이디어를 대화당 하나씩(그 대화의
         *     가장 최근 아이디어) 만든 날짜의 역순으로 최대 limit개 주고, 항목마다 그 대화의 종류별 노트
         *     개수를 붙인다. 없으면 빈 목록.
         */
        get: operations["open_ideas_api_notes_open_ideas_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/notes/{note_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Update Note
         * @description 별표·완료·내용 중 보낸 필드만 바꾼다. 보낸 필드에 null은 쓸 수 없다.
         */
        patch: operations["update_note_api_notes__note_id__patch"];
        trace?: never;
    };
    "/api/sessions/{session_id}/turns/{turn_id}/latency": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Report Latency */
        post: operations["report_latency_api_sessions__session_id__turns__turn_id__latency_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/latency": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Latency */
        get: operations["get_latency_api_latency_get"];
        put?: never;
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
        /** AckOut */
        AckOut: {
            /** Text */
            text: string;
            /** Audio */
            audio: string | null;
        };
        /**
         * AttachmentOut
         * @description 턴에 붙은 첨부(M5). 파일은 GET /api/attachments/{id}(썸네일은 ?thumb=1).
         */
        AttachmentOut: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Mime */
            mime: string;
            /** Size */
            size: number;
            /** Thumb */
            thumb: boolean;
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
        /** CitationOut */
        CitationOut: {
            /** N */
            n: number;
            /** Title */
            title: string;
            /** Url */
            url: string;
        };
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
        /** JournalDetail */
        JournalDetail: {
            session: components["schemas"]["JournalItem"];
            /** Summary Cites */
            summary_cites: number[][];
            /** Citations */
            citations: components["schemas"]["CitationOut"][];
            /** Checks */
            checks: string[] | null;
            /** Persona Name */
            persona_name: string;
            /** Notes */
            notes: components["schemas"]["NoteOut"][];
            /** Turns */
            turns: components["schemas"]["TurnOut"][];
        };
        /** JournalItem */
        JournalItem: {
            /** Id */
            id: string;
            /**
             * Date
             * Format: date
             */
            date: string;
            /**
             * Started At
             * Format: date-time
             */
            started_at: string;
            /** Ended At */
            ended_at: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "active" | "paused" | "ended";
            /** Title */
            title: string | null;
            /** Summary */
            summary: string[];
            /** Tags */
            tags: string[];
            /** Journal Status */
            journal_status: ("pending" | "done" | "failed") | null;
            counts: components["schemas"]["NoteCounts"];
        };
        /** JournalPatch */
        JournalPatch: {
            /** Title */
            title: string;
        };
        /** LatencyOut */
        LatencyOut: {
            /** Turns */
            turns: components["schemas"]["LatencyTurn"][];
            summary: components["schemas"]["LatencySummary"];
        };
        /**
         * LatencyReport
         * @description 클라이언트가 턴마다 한 번 보고하는 값(0~600000ms).
         */
        LatencyReport: {
            /** Speech To Request Ms */
            speech_to_request_ms: number;
            /** Request To Playback Ms */
            request_to_playback_ms: number;
            /**
             * First Sound Notice
             * @default false
             */
            first_sound_notice: boolean;
            /** Ack Ms */
            ack_ms?: number | null;
        };
        /** LatencySummary */
        LatencySummary: {
            /** Count */
            count: number;
            total_ms: components["schemas"]["Stat"] | null;
            total_ms_reply: components["schemas"]["Stat"] | null;
            /** Stages */
            stages: {
                [key: string]: number;
            };
            ack_ms: components["schemas"]["Stat"] | null;
            search: components["schemas"]["TotalStats"];
            tts: components["schemas"]["TtsStats"];
        };
        /** LatencyTurn */
        LatencyTurn: {
            /** Turn Id */
            turn_id: string;
            /** Upload Ms */
            upload_ms: number | null;
            /** Stt Ms */
            stt_ms: number | null;
            /** First Token Ms */
            first_token_ms: number | null;
            /** First Queued Ms */
            first_queued_ms: number | null;
            /** First Synth Ms */
            first_synth_ms: number | null;
            /** Synth Wait Ms */
            synth_wait_ms: number | null;
            /** First Sentence Ms */
            first_sentence_ms: number | null;
            /** Done Ms */
            done_ms: number | null;
            /** Audio Bytes */
            audio_bytes: number | null;
            /** Cli Age Ms */
            cli_age_ms: number | null;
            /** Reply Chars */
            reply_chars: number | null;
            /** Searched */
            searched: boolean;
            /** Speech To Request Ms */
            speech_to_request_ms: number | null;
            /** Request To Playback Ms */
            request_to_playback_ms: number | null;
            /** First Sound Notice */
            first_sound_notice: boolean | null;
            /** Ack Ms */
            ack_ms: number | null;
            /** Total Ms */
            total_ms: number | null;
        };
        /** NoteCounts */
        NoteCounts: {
            /** Idea */
            idea: number;
            /** Todo */
            todo: number;
            /** Memo */
            memo: number;
        };
        /** NoteOut */
        NoteOut: {
            /** Id */
            id: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "idea" | "todo" | "memo";
            /** Content */
            content: string;
            /** Starred */
            starred: boolean;
            /** Done */
            done: boolean;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Cites */
            cites: number[];
        };
        /**
         * NotePatch
         * @description 보낸 필드만 바꾼다.
         */
        NotePatch: {
            /** Starred */
            starred?: boolean | null;
            /** Done */
            done?: boolean | null;
            /** Content */
            content?: string | null;
        };
        /** OpenIdea */
        OpenIdea: {
            /** Id */
            id: string;
            /** Content */
            content: string;
            /** Starred */
            starred: boolean;
            /** Session Id */
            session_id: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            counts: components["schemas"]["NoteCounts"];
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
         *     journal_status는 일지 정리 상태다. pending이면 기다리는 시간 안에 정리가 끝나지 않은 것이다
         *     (개수가 나중에 늘 수 있다). null은 정리 기록이 없는 것이다.
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
        /** SessionReopen */
        SessionReopen: {
            /**
             * Mode
             * @default text
             * @enum {string}
             */
            mode: "text" | "voice";
        };
        /**
         * SessionReopened
         * @description 다시 열기 응답. greeting은 전문 끝에 새로 남긴 재개 인사말(호칭 없음), turns는 그 인사말까지
         *     포함한 전체 전문(일지 상세의 turns와 같은 형식)이다.
         */
        SessionReopened: {
            session: components["schemas"]["SessionOut"];
            greeting: components["schemas"]["GreetingOut"];
            persona: components["schemas"]["PersonaOut"];
            /** Turns */
            turns: components["schemas"]["TurnOut"][];
        };
        /** SessionStarted */
        SessionStarted: {
            session: components["schemas"]["SessionOut"];
            greeting: components["schemas"]["GreetingOut"];
            persona: components["schemas"]["PersonaOut"];
        };
        /** Stat */
        Stat: {
            /** Median */
            median: number;
            /** P90 */
            p90: number;
        };
        /** TotalStats */
        TotalStats: {
            /** Count */
            count: number;
            total_ms: components["schemas"]["Stat"] | null;
            total_ms_reply: components["schemas"]["Stat"] | null;
        };
        /** TtsStats */
        TtsStats: {
            /** Models */
            models: {
                [key: string]: number;
            };
            /** Fallback Ratio */
            fallback_ratio: number;
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
        /** TurnOut */
        TurnOut: {
            /** Id */
            id: string;
            /** Seq */
            seq: number;
            /**
             * Role
             * @enum {string}
             */
            role: "user" | "assistant";
            /** Text */
            text: string;
            /** Interrupted */
            interrupted: boolean;
            /** Merged From */
            merged_from: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Attachments */
            attachments: components["schemas"]["AttachmentOut"][];
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
         * TranscriptEvent
         * @description 음성 턴에서만 `turn` 바로 앞에 오는 첫 이벤트. 인식한 글(사용자 메시지로 저장된 글)이다.
         */
        TranscriptEvent: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "transcript";
            /** Text */
            text: string;
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
        StreamEvent: components["schemas"]["TranscriptEvent"] | components["schemas"]["TurnEvent"] | components["schemas"]["SentenceEvent"] | components["schemas"]["ToolEvent"] | components["schemas"]["DoneEvent"] | components["schemas"]["ErrorEvent"];
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
    reopen_session_api_sessions__session_id__reopen_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["SessionReopen"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionReopened"];
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
    create_audio_turn_api_sessions__session_id__turns_audio_post: {
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
            /** @description 음성 턴 이벤트 스트림(transcript → turn → sentence·tool → done 또는 error) */
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
    list_journal_api_journal_get: {
        parameters: {
            query?: {
                from?: string | null;
                to?: string | null;
            };
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
                    "application/json": components["schemas"]["JournalItem"][];
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
    get_journal_api_journal__session_id__get: {
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
                    "application/json": components["schemas"]["JournalDetail"];
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
    delete_journal_api_journal__session_id__delete: {
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
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
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
    update_journal_api_journal__session_id__patch: {
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
                "application/json": components["schemas"]["JournalPatch"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JournalItem"];
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
    retry_journal_api_journal__session_id__retry_post: {
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
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JournalItem"];
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
    open_ideas_api_notes_open_ideas_get: {
        parameters: {
            query?: {
                limit?: number;
            };
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
                    "application/json": components["schemas"]["OpenIdea"][];
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
    update_note_api_notes__note_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                note_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NotePatch"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NoteOut"];
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
    report_latency_api_sessions__session_id__turns__turn_id__latency_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
                turn_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LatencyReport"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
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
    get_latency_api_latency_get: {
        parameters: {
            query?: {
                limit?: number;
            };
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
                    "application/json": components["schemas"]["LatencyOut"];
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
