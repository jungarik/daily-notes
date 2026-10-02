
import { visibleViewport } from "/sessions/rcw-01cjbbgzg5szrkemdd9v4ptz/mnt/daily-notes/browser/webapp/src/lib/format.js";
const cases = JSON.parse(process.argv[2]);
console.log(JSON.stringify(cases.map(visibleViewport)));
