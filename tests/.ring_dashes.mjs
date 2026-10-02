
import { ringDashes, RING_MAX_SEGMENTS, formatCount, COUNT_CAP } from "/sessions/rcw-01cjbbgzg5szrkemdd9v4ptz/mnt/daily-notes/browser/webapp/src/lib/format.js";
const counts = JSON.parse(process.argv[2]);
console.log(JSON.stringify({
  cap: RING_MAX_SEGMENTS,
  countCap: COUNT_CAP,
  rings: counts.map((n) => ringDashes(n, 193.20794819577227, 2.5)),
  labels: counts.map(formatCount),
}));
