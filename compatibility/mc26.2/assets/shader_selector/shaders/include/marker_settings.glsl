
// define distinct values, counting from 1:
#define SCREENSHAKE_FREQUENCY 1
#define SCREENSHAKE_MAGNITUDE 2
#define ALARM_EFFECTS 3

/*
signature:
 ADD_MARKER(channel, green, alpha, op, rate)
*/
// append different marker definitions
#define LIST_MARKERS  ADD_MARKER(SCREENSHAKE_FREQUENCY, 253, 0, 1, 10)  ADD_MARKER(SCREENSHAKE_MAGNITUDE, 252, 0, 1, 10)  ADD_MARKER(ALARM_EFFECTS, 251, 0, 0, 10)  
#define MARKER_RED 254

// Screen pixel that the marker ends up on if it uses channel k:
// Mapping follows structure that is like an inverted cantor pairing (but only producing coordinates with an even sum)
#define MARKER_POS(k) (ivec2(2*int(ceil(sqrt(float(k))) - 1.0),0) + (k - int((ceil(sqrt(float(k))) - 1.0)*(ceil(sqrt(float(k))) - 1.0)) - 1)*ivec2(-1, 1))
