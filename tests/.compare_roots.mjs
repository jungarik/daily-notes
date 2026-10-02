
import { compareRoots } from "/sessions/rcw-01cjbbgzg5szrkemdd9v4ptz/mnt/daily-notes/browser/webapp/src/lib/format.js";
const [roots, names] = JSON.parse(process.argv[2]);
console.log(JSON.stringify(names.sort(compareRoots(roots))));
