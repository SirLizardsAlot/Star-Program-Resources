// Legacy marker identities remain unchanged.
#define SCREENSHAKE_FREQUENCY 1
#define SCREENSHAKE_MAGNITUDE 2
#define ALARM_EFFECTS 3
#define SKY_TIME_HIGH 4
#define SKY_TIME_LOW 5
#define ZOOM_AMOUNT 6
#define RESERVED_CONTROL 7
#define SP_CHANNEL_COUNT 7
#define MARKER_RED 254
#define LIST_MARKERS ADD_MARKER(SCREENSHAKE_FREQUENCY,253,0,1,10) ADD_MARKER(SCREENSHAKE_MAGNITUDE,252,0,1,10) ADD_MARKER(ALARM_EFFECTS,251,0,0,10)
#define MARKER_POS(k) (ivec2(2*int(ceil(sqrt(float(k)))-1.0),0)+(k-int((ceil(sqrt(float(k)))-1.0)*(ceil(sqrt(float(k)))-1.0))-1)*ivec2(-1,1))
#define SP_MARKER_POS(channel,sequence) ivec2(40+(sequence)%64,((channel)-4)*2+(sequence)/64)
