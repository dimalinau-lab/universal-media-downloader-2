// Функция отправки ссылки в Universal Media Downloader
function sendToUMD(url, quality = '') {
  fetch('http://127.0.0.1:65432/download', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ url: url, quality: quality })
  })
  .then(response => response.json())
  .then(data => {
    console.log("Успешно отправлено в UMD:", data);
    chrome.action.setBadgeText({text: "OK!"});
    chrome.action.setBadgeBackgroundColor({color: '#22c55e'});
    setTimeout(() => chrome.action.setBadgeText({text: ""}), 2500);
  })
  .catch(err => {
    console.error("Ошибка (UMD не запущен?):", err);
    chrome.action.setBadgeText({text: "ERR"});
    chrome.action.setBadgeBackgroundColor({color: '#ef4444'});
    setTimeout(() => chrome.action.setBadgeText({text: ""}), 2500);
  });
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "send_to_umd",
    title: "Скачать видео через UMD",
    contexts: ["page", "link", "video", "audio"]
  });
  chrome.contextMenus.create({
    id: "send_to_umd_audio",
    title: "Скачать аудио (MP3) через UMD",
    contexts: ["page", "link", "video", "audio"]
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  let targetUrl = info.linkUrl || info.srcUrl || info.pageUrl;
  if (targetUrl) {
    chrome.action.setBadgeText({text: "..."});
    let quality = (info.menuItemId === "send_to_umd_audio") ? "audio_mp3" : "";
    sendToUMD(targetUrl, quality);
  }
});