/* AI Meeting Intelligence — in-browser live notes.
 *
 * The Jitsi call runs in a cross-origin iframe, so we can't read its audio.
 * Instead each participant's browser transcribes THEIR OWN microphone with the
 * free Web Speech API and posts final snippets to the server, which stitches
 * everyone together into one speaker-labeled transcript. A live panel shows the
 * merged captions (pushed over Pusher). On leave, the organizer's browser asks
 * the server to summarize and is sent to the review screen.
 *
 * Expects window.MEETING_CTX = {
 *   meetingId, userId, csrfToken, pusherKey, pusherCluster,
 *   segmentUrl, finalizeUrl, reviewUrl, notesUrl, calendarUrl, canManage
 * } and calls from the room template: MeetingIntel.attach(api) and, on
 * videoConferenceLeft, MeetingIntel.handleLeave().
 */
(function () {
  var ctx = window.MEETING_CTX || {};
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;

  var recognition = null;
  var shouldRun = false;   // we want recognition active
  var joined = false;      // currently in the call
  var muted = false;       // muted in Jitsi → don't transcribe
  var finishing = false;   // leave already in progress
  var seq = 0;
  var buffer = [];
  var flushTimer = null;

  // ── tiny DOM helpers (all output via textContent — no HTML injection) ──
  function el(id) { return document.getElementById(id); }

  function setStatus(text, state) {
    var s = el('liveNotesStatus');
    if (s) { s.textContent = text; s.setAttribute('data-state', state || ''); }
  }

  function appendCaption(name, text, mine) {
    var feed = el('captionFeed');
    if (!feed || !text) return;
    var empty = el('captionEmpty');
    if (empty) empty.style.display = 'none';
    var line = document.createElement('div');
    line.className = 'caption-line' + (mine ? ' mine' : '');
    var who = document.createElement('span');
    who.className = 'caption-who';
    who.textContent = (name || 'Speaker') + ': ';
    var body = document.createElement('span');
    body.textContent = text;
    line.appendChild(who);
    line.appendChild(body);
    feed.appendChild(line);
    feed.scrollTop = feed.scrollHeight;
  }

  function showInterim(text) {
    var i = el('captionInterim');
    if (i) i.textContent = text || '';
  }

  // ── speech recognition ──
  function buildRecognition() {
    var r = new SR();
    r.continuous = true;
    r.interimResults = true;
    r.lang = navigator.language || 'en-US';

    r.onresult = function (e) {
      var interim = '';
      for (var i = e.resultIndex; i < e.results.length; i++) {
        var res = e.results[i];
        var text = (res[0] && res[0].transcript ? res[0].transcript : '').trim();
        if (!text) continue;
        if (res.isFinal) {
          buffer.push({ seq: seq++, text: text, started_at: new Date().toISOString() });
          scheduleFlush();
          appendCaption('You', text, true);
        } else {
          interim = text;
        }
      }
      showInterim(interim);
    };

    r.onerror = function (ev) {
      var err = ev && ev.error;
      if (err === 'not-allowed' || err === 'service-not-allowed') {
        shouldRun = false;
        setStatus('Live notes off (microphone blocked)', 'off');
      }
      // 'no-speech' / 'aborted' are transient — onend will restart.
    };

    // The engine stops itself periodically; restart while we're still talking.
    r.onend = function () {
      if (shouldRun && joined && !muted) {
        setTimeout(function () { try { r.start(); } catch (e) {} }, 300);
      }
    };
    return r;
  }

  function startSTT() {
    if (!SR) return;
    if (!recognition) recognition = buildRecognition();
    shouldRun = true;
    try { recognition.start(); } catch (e) { /* already started */ }
    setStatus('Live notes recording', 'on');
  }

  function stopSTT() {
    shouldRun = false;
    if (recognition) { try { recognition.stop(); } catch (e) {} }
  }

  // ── batched upload of final segments ──
  function scheduleFlush() {
    if (buffer.length >= 5) { flush(); return; }
    if (!flushTimer) flushTimer = setTimeout(flush, 3000);
  }

  function flush() {
    if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
    if (!buffer.length || !ctx.segmentUrl) return Promise.resolve();
    var batch = buffer.splice(0, buffer.length);
    return fetch(ctx.segmentUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': ctx.csrfToken },
      body: JSON.stringify({ segments: batch })
    }).then(function (r) {
      if (!r.ok) throw new Error('segment post failed');
    }).catch(function () {
      buffer = batch.concat(buffer);  // requeue on failure
    });
  }

  // ── Jitsi wiring ──
  function attach(api) {
    if (!api) return;
    try {
      api.addEventListener('videoConferenceJoined', function () {
        joined = true;
        if (SR) startSTT();
      });
      api.addEventListener('audioMuteStatusChanged', function (e) {
        muted = !!(e && e.muted);
        if (muted) stopSTT();
        else if (joined && SR) startSTT();
      });
    } catch (e) { /* older external_api */ }
    window.addEventListener('beforeunload', function () { try { flush(); } catch (e) {} });
  }

  function handleLeave() {
    if (finishing) { return; }
    finishing = true;
    joined = false;
    stopSTT();

    var go = function () {
      if (ctx.canManage && ctx.finalizeUrl) {
        setStatus('Generating notes…', 'on');
        fetch(ctx.finalizeUrl, {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': ctx.csrfToken },
          body: '{}'
        }).then(function (r) {
          return r.json().catch(function () { return {}; });
        }).then(function (d) {
          window.location.href = (d && d.redirect) || ctx.notesUrl || ctx.calendarUrl;
        }).catch(function () {
          window.location.href = ctx.notesUrl || ctx.calendarUrl;
        });
      } else {
        window.location.href = ctx.calendarUrl;
      }
    };
    Promise.resolve(flush()).then(go, go);
  }

  // ── live merged-caption panel (Pusher) ──
  function setupLivePanel() {
    if (!ctx.pusherKey || ctx.pusherKey.indexOf('your-') !== -1 || !window.Pusher) return;
    try {
      var pusher = new Pusher(ctx.pusherKey, { cluster: ctx.pusherCluster, forceTLS: true });
      var channel = pusher.subscribe('meeting-' + ctx.meetingId);
      channel.bind('caption-final', function (data) {
        if (!data || data.user_id === ctx.userId) return;  // own lines already shown
        appendCaption(data.name, data.text, false);
      });
    } catch (e) { /* live panel is a nicety; persistence is server-side */ }
  }

  // ── init ──
  if (!SR) {
    setStatus('Live notes off — open in Chrome or Edge to capture this meeting', 'off');
  } else {
    setStatus('Live notes ready', 'idle');
  }
  setupLivePanel();

  window.MeetingIntel = { attach: attach, handleLeave: handleLeave };
})();
