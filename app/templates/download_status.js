// The cookie acknowledges response headers, never a completed browser disk save.
(() => {
  const status = document.getElementById("downloadStatus");
  const submit = downloadForm.querySelector("button[type='submit']");
  const timeoutMs = 300000;
  let active = null;

  function clearCookie(attempt){
    document.cookie = `${attempt.cookie}=; Max-Age=0; Path=/; SameSite=Lax`;
  }

  function finish(attempt, message, error = false){
    if(active !== attempt){return;}
    clearInterval(attempt.timer);
    clearCookie(attempt);
    active = null;
    submit.disabled = false;
    status.textContent = message;
    logToTerminal(message);
    if(error){showError(message);}
    attempt.frame.remove();
  }

  function inspectError(attempt, loaded = false){
    if(active !== attempt){return;}
    try {
      const doc = attempt.frame.contentDocument;
      const error = doc && doc.querySelector("[data-download-error]");
      if(error){
        if(error.dataset.downloadToken === attempt.token){finish(attempt, error.textContent, true);}
      } else if(loaded && doc && doc.body && doc.body.textContent.trim()){
        // Framework/proxy HTTP errors may not carry our HTML error envelope.
        finish(attempt, "The download request was rejected. Check your selection and retry, or sign in again.", true);
      }
    } catch (_error) {
      if(loaded){finish(attempt, "Could not read the download response. Sign in again and retry.", true);}
    }
  }

  downloadForm.addEventListener("submit", (event) => {
    if(active){event.preventDefault(); return;}
    const count = downloadForm.querySelectorAll("input[name='file_ids']:checked").length;
    if(!count){
      event.preventDefault();
      showError("Select at least one file to download.");
      return;
    }
    const token = Array.from(crypto.getRandomValues(new Uint8Array(16)),
      byte => byte.toString(16).padStart(2, "0")).join("");
    const frame = document.createElement("iframe");
    frame.name = `download_${token}`;
    frame.hidden = true;
    frame.title = "Download response";
    const attempt = {token, frame, cookie: `download_status_${token}`, started: Date.now()};
    active = attempt;
    document.getElementById("errorBanner").classList.add("hidden");
    clearCookie(attempt);
    frame.addEventListener("load", () => inspectError(attempt, true));
    document.body.append(frame);
    downloadForm.setAttribute("target", frame.name);
    const deadline = Math.floor((attempt.started + timeoutMs) / 1000);
    downloadForm.setAttribute("action", `/download?download_token=${token}&download_deadline=${deadline}`);
    submit.disabled = true;
    function poll(){
      if(active !== attempt){return;}
      const elapsed = Date.now() - attempt.started;
      status.textContent = `Preparing ${count} file${count === 1 ? "" : "s"}… ${Math.floor(elapsed / 1000)}s elapsed`;
      const ready = document.cookie.split(";").some(value => value.trim() === `${attempt.cookie}=ready`);
      if(ready){
        finish(attempt, "Download response is ready. Check your browser’s downloads for transfer and save status.");
      } else if(elapsed >= timeoutMs){
        finish(attempt, "Still no download response after 5 minutes. Server preparation may still be running; check browser downloads before retrying.", true);
      } else {
        inspectError(attempt);
      }
    }
    attempt.timer = setInterval(poll, 250);
    poll();
  });

  window.addEventListener("pagehide", () => {
    if(active){
      clearInterval(active.timer);
      clearCookie(active);
      active.frame.remove();
      active = null;
      submit.disabled = false;
    }
  });
})();
