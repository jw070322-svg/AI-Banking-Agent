/* Keep existing buttons and their handlers; only relocate their DOM nodes. */
(function () {
  'use strict';
  const root = document.getElementById('bank-app');
  if (!root) return;
  const toolbar = document.createElement('nav');
  toolbar.className = 'service-toolbar';
  toolbar.setAttribute('aria-label', '服务工具');
  let features, summary;
  function place() {
    features = features || document.getElementById('feature-launchers');
    summary = summary || document.getElementById('experience-launcher');
    const header = root.querySelector('.app-header');
    if (!header || !features || !summary) return;
    if (features.parentNode !== toolbar) toolbar.append(features);
    if (summary.parentNode !== toolbar) toolbar.append(summary);
    // Keep these independently managed controls outside bank-app: its network
    // listener snapshots disabled states and would conflict with their own
    // request-state listener. Align to main without entering that ownership.
    const offset = getComputedStyle(header.parentElement).marginLeft;
    if (toolbar.style.getPropertyValue('--main-offset') !== offset)
      toolbar.style.setProperty('--main-offset', offset);
    if (root.previousElementSibling !== toolbar) root.before(toolbar);
  }
  const observer = new MutationObserver(place);
  observer.observe(document.body, {childList: true, subtree: true});
  window.addEventListener('resize', place);
  place();
})();
