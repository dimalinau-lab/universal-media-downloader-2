let currentTabUrl = '';

function checkUmdStatus() {
  const badge = document.getElementById('statusBadge');
  fetch('http://127.0.0.1:65432/status')
    .then(r => r.json())
    .then(data => {
      badge.textContent = '🟢 На связи';
      badge.className = 'status-badge status-online';
    })
    .catch(() => {
      badge.textContent = '🔴 Не запущен';
      badge.className = 'status-badge status-offline';
    });
}

function showNotify(msg, isSuccess) {
  const box = document.getElementById('notifyBox');
  box.textContent = msg;
  box.className = 'notify ' + (isSuccess ? 'notify-success' : 'notify-error');
  box.style.display = 'block';
  setTimeout(() => {
    box.style.display = 'none';
  }, 3500);
}

function sendDownload(quality = '') {
  if (!currentTabUrl || (!currentTabUrl.startsWith('http://') && !currentTabUrl.startsWith('https://'))) {
    showNotify('Некорректный адрес страницы', false);
    return;
  }

  const btnVideo = document.getElementById('btnDownloadVideo');
  const btnAudio = document.getElementById('btnDownloadAudio');
  btnVideo.disabled = true;
  btnAudio.disabled = true;

  fetch('http://127.0.0.1:65432/download', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: currentTabUrl, quality: quality })
  })
    .then(r => r.json())
    .then(data => {
      if (data.status === 'success') {
        showNotify('✅ Отправлено в очередь UMD!', true);
        chrome.action.setBadgeText({ text: 'OK' });
        chrome.action.setBadgeBackgroundColor({ color: '#22c55e' });
        setTimeout(() => chrome.action.setBadgeText({ text: '' }), 3000);
      } else {
        showNotify('Ошибка: ' + (data.message || 'Сбой запроса'), false);
      }
    })
    .catch(err => {
      showNotify('UMD не запущен на компьютере', false);
      chrome.action.setBadgeText({ text: 'ERR' });
      chrome.action.setBadgeBackgroundColor({ color: '#ef4444' });
      setTimeout(() => chrome.action.setBadgeText({ text: '' }), 3000);
    })
    .finally(() => {
      setTimeout(() => {
        btnVideo.disabled = false;
        btnAudio.disabled = false;
      }, 1000);
    });
}

document.addEventListener('DOMContentLoaded', () => {
  checkUmdStatus();

  chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
    if (tabs && tabs[0]) {
      const tab = tabs[0];
      currentTabUrl = tab.url || '';
      document.getElementById('pageTitle').textContent = tab.title || 'Текущая вкладка';
      document.getElementById('pageUrl').textContent = currentTabUrl;
    }
  });

  document.getElementById('btnDownloadVideo').addEventListener('click', () => {
    sendDownload('');
  });

  document.getElementById('btnDownloadAudio').addEventListener('click', () => {
    sendDownload('audio_mp3');
  });
});
