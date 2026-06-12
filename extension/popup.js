// popup: 활성화 토글 + 허용 채널(whitelist) 관리

const $enabled = document.getElementById('enabled');
const $list = document.getElementById('whitelist');

function render(whitelist) {
  $list.innerHTML = '';
  if (!whitelist.length) {
    $list.innerHTML = '<li class="empty">없음</li>';
    return;
  }
  for (const ch of whitelist) {
    const li = document.createElement('li');
    const span = document.createElement('span');
    span.textContent = ch;
    const btn = document.createElement('button');
    btn.textContent = '해제';
    btn.addEventListener('click', () => {
      chrome.storage.local.get({ whitelist: [] }, (d) => {
        const next = d.whitelist.filter((x) => x !== ch);
        chrome.storage.local.set({ whitelist: next }, () => render(next));
      });
    });
    li.append(span, btn);
    $list.appendChild(li);
  }
}

chrome.storage.local.get({ enabled: true, whitelist: [] }, (d) => {
  $enabled.checked = d.enabled;
  render(d.whitelist);
});

$enabled.addEventListener('change', () => {
  chrome.storage.local.set({ enabled: $enabled.checked });
});
