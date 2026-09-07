import { readFileSync } from 'node:fs';
import vm from 'node:vm';

// Execute the actual template's pure parser/grading functions. This keeps the
// student implementation under test instead of copying its logic into tests.
const template = readFileSync(new URL('../../../../templates/courses/episodes/_tabs_quiz.html', import.meta.url), 'utf8');
const start = template.indexOf('    function cbaTokensEquivalent(');
const end = template.lastIndexOf('    initWhenReady();');
if (start < 0 || end <= start) throw new Error('Student quiz function boundaries changed');
const scope = {};
vm.runInNewContext(template.slice(start, end) + '\nthis.exports = {parseQuiz, cbaTokensEquivalent, isCBACorrect};', scope);
export const studentQuiz = scope.exports;
