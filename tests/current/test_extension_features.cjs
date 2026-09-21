const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const calls = [];
let download = {id: 5, state: 'interrupted', url: 'https://files.test/beat.wav', canResume: false};
const context = {chrome: {
  declarativeNetRequest: {
    getDynamicRules: async () => [{id: 9}],
    updateDynamicRules: async p => calls.push(['rules', p]),
    updateEnabledRulesets: async p => calls.push(['enabled', p]),
  },
  downloads: {
    search: async p => p.id === 999 ? [] : [download],
    cancel: async id => calls.push(['cancel', id]),
    resume: async id => calls.push(['resume', id]),
    show: id => calls.push(['show', id]),
    open: async id => calls.push(['open', id]),
    pause: async id => calls.push(['pause', id]),
    erase: async q => calls.push(['erase', q]),
    download: async p => { calls.push(['download', p]); return 6; },
  },
}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../../chromium_zoom_extension/features.js'), 'utf8'), context);
(async () => {
  const run = context.tekziteFeature;
  await run('configure', {enabled: true, sites: ['example.test', 'example.test', 'bad/path']});
  assert.equal(calls[0][1].addRules.length, 1);
  assert.equal(calls[0][1].addRules[0].action.type, 'allowAllRequests');
  assert.equal(calls[0][1].addRules[0].condition.resourceTypes[0], 'main_frame');
  assert.equal(calls[0][1].addRules[0].condition.requestDomains[0], 'example.test');
  assert.equal(calls[0][1].removeRuleIds[0], 9);
  assert.equal(calls[1][1].enableRulesetIds[0], 'ads');
  await run('configure', {enabled: false, sites: []});
  assert.equal(calls.at(-1)[1].disableRulesetIds[0], 'ads');
  assert.equal((await run('downloads', {}))[0].id, 5);
  await run('cancel', {id: 5}); assert.equal(calls.at(-1)[0], 'cancel');
  await run('show', {id: 5}); assert.equal(calls.at(-1)[0], 'show');
  download.state = 'complete'; download.danger = 'safe';
  await run('open', {id: 5}); assert.equal(calls.at(-1)[0], 'open');
  download.danger = 'dangerous'; await assert.rejects(run('open', {id: 5}), /blocked opening/);
  download.danger = 'safe'; download.state = 'interrupted';
  await run('pause', {id: 5}); assert.equal(calls.at(-1)[0], 'pause');
  await run('erase', {id: 5}); assert.equal(calls.at(-1)[0], 'erase');
  await run('retry', {id: 5}); assert.equal(calls.at(-1)[1].conflictAction, 'uniquify');
  download.canResume = true;
  await run('retry', {id: 5}); assert.equal(calls.at(-1)[0], 'resume');
  download.canResume = false; download.url = 'blob:https://files.test/id';
  await assert.rejects(run('retry', {id: 5}), /original page/);
  await assert.rejects(run('cancel', {id: 999}), /no longer/);
  await assert.rejects(run('execute', {id: 5}), /Unknown/);
  console.log('Extension feature checks passed (mocked Chrome APIs).');
})().catch(error => { console.error(error); process.exitCode = 1; });
