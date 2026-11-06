/* Synthetic qualification completion, not a provider audio-done event. */
(() => {
  function ready({now,inputEnded,backendSettled,backendResultAt,lastSpeechAt,expectedCovered,quietMs=3500}) {
    return inputEnded===true && backendSettled===true && expectedCovered===true
      && Number.isFinite(backendResultAt) && Number.isFinite(lastSpeechAt)
      && lastSpeechAt>=backendResultAt && now-lastSpeechAt>=quietMs;
  }
  if(typeof window!=='undefined')window.LiveSemanticTail={ready};
  if(typeof module!=='undefined'){
    module.exports={ready};
    if(require.main===module){
      const assert=require('node:assert/strict');
      const base={now:20000,inputEnded:true,backendSettled:true,backendResultAt:19000,lastSpeechAt:5000,expectedCovered:true};
      assert.equal(ready(base),false,'An old acknowledgment cannot end a newly completed delegation');
      assert.equal(ready({...base,lastSpeechAt:19500}),false,'Do not truncate newly returned speech');
      assert.equal(ready({...base,now:24000,lastSpeechAt:19500}),true);
      assert.equal(ready({...base,now:24000,lastSpeechAt:19500,backendSettled:false}),false);
      assert.equal(ready({...base,now:24000,lastSpeechAt:19500,inputEnded:false}),false);
      assert.equal(ready({...base,now:24000,lastSpeechAt:19500,expectedCovered:false}),false,'A pause after half an answer cannot establish semantic completion');
      console.log('Synthetic Live completion requires ended input, settled work and a post-result spoken quiet tail.');
    }
  }
})();
