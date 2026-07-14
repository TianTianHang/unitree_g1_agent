string EVENT_ASR="asr"
string EVENT_PLAYBACK="playback"
int8 PLAYBACK_STOPPED=0
int8 PLAYBACK_PLAYING=1

builtin_interfaces/Time stamp
string source
string event_type
bool has_sequence_id
uint64 sequence_id
string text
bool has_confidence
float32 confidence
bool is_final
string language
bool has_playback_state
int8 playback_state
