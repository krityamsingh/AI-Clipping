// AI Video Clipping & Editing Engine Frontend JavaScript

let pollInterval = null;

// Switch Source Tabs
function switchSourceTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

  if (tabName === 'local') {
    document.querySelectorAll('.tab-btn')[0].classList.add('active');
    document.getElementById('tab-local').classList.add('active');
  } else if (tabName === 'upload') {
    document.querySelectorAll('.tab-btn')[1].classList.add('active');
    document.getElementById('tab-upload').classList.add('active');
  } else if (tabName === 'url') {
    document.querySelectorAll('.tab-btn')[2].classList.add('active');
    document.getElementById('tab-url').classList.add('active');
  }
}

// Refresh Raw Videos List
async function refreshRawVideos() {
  const select = document.getElementById('local-video-select');
  select.innerHTML = '<option value="">Scanning raw/ directory...</option>';
  try {
    const res = await fetch('/api/raw-videos');
    const data = await res.json();
    select.innerHTML = '';
    if (!data.videos || data.videos.length === 0) {
      select.innerHTML = '<option value="">No videos in raw/ directory</option>';
      return;
    }
    data.videos.forEach(v => {
      const opt = document.createElement('option');
      opt.value = v.path;
      opt.textContent = `${v.name} (${v.size_mb} MB)`;
      select.appendChild(opt);
    });
  } catch (err) {
    select.innerHTML = `<option value="">Error scanning raw/: ${err.message}</option>`;
  }
}

// Upload Video File
async function uploadVideoFile() {
  const fileInput = document.getElementById('video-file-input');
  if (!fileInput.files || fileInput.files.length === 0) {
    alert('Please choose a video file to upload.');
    return;
  }
  const file = fileInput.files[0];
  const formData = new FormData();
  formData.append('file', file);

  const progContainer = document.getElementById('upload-progress');
  const progFill = document.getElementById('upload-progress-fill');
  progContainer.classList.remove('hidden');
  progFill.style.width = '30%';

  try {
    const res = await fetch('/api/upload', {
      method: 'POST',
      body: formData
    });
    progFill.style.width = '100%';
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Upload failed');
    alert(`File uploaded successfully: ${data.filename}`);
    switchSourceTab('local');
    await refreshRawVideos();
    document.getElementById('local-video-select').value = data.path;
  } catch (err) {
    alert(`Upload error: ${err.message}`);
  } finally {
    setTimeout(() => {
      progContainer.classList.add('hidden');
      progFill.style.width = '0%';
    }, 1500);
  }
}

// Download Video From URL
async function downloadVideoFromUrl() {
  const input = document.getElementById('video-url-input');
  const url = input.value.trim();
  if (!url) {
    alert('Please enter a valid video link.');
    return;
  }

  appendLog(`Downloading web video: ${url}...`);
  try {
    const res = await fetch('/api/download-url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: url })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Download failed');
    appendLog(`Downloaded video saved to: ${data.path}`);
    alert(`Downloaded successfully: ${data.filename}`);
    switchSourceTab('local');
    await refreshRawVideos();
    document.getElementById('local-video-select').value = data.path;
  } catch (err) {
    appendLog(`Download error: ${err.message}`);
    alert(`Download error: ${err.message}`);
  }
}

// Append text to Logs console
function appendLog(msg) {
  const logsEl = document.getElementById('logs-output');
  const timestamp = new Date().toLocaleTimeString();
  logsEl.textContent += `\n[${timestamp}] ${msg}`;
  logsEl.scrollTop = logsEl.scrollHeight;
}

// Start Clipping Pipeline
async function startClippingPipeline() {
  let sourceVideo = '';
  const localSelect = document.getElementById('local-video-select');
  if (localSelect.value) {
    sourceVideo = localSelect.value;
  } else {
    alert('Please select or upload a video file first.');
    return;
  }

  const payload = {
    source: sourceVideo,
    target_duration: parseFloat(document.getElementById('clip-duration').value),
    num_clips: parseInt(document.getElementById('num-clips').value, 10),
    aspect_ratio: document.getElementById('aspect-ratio').value,
    layout_style: document.getElementById('layout-style').value,
    export_quality: document.getElementById('export-quality').value,
    whisper_model: document.getElementById('whisper-model').value,
    burn_captions: document.getElementById('opt-captions').checked,
    word_highlight: document.getElementById('opt-word-highlight').checked,
    normalize_audio: document.getElementById('opt-loudnorm').checked,
    color_correction: document.getElementById('opt-color').checked,
    zoom_effect: document.getElementById('opt-zoom').checked
  };

  const btn = document.getElementById('btn-start');
  btn.disabled = true;
  btn.textContent = '⏳ Processing Video Highlights...';

  const progContainer = document.getElementById('progress-container');
  progContainer.classList.remove('hidden');
  updateProgress(5, 'Starting processing engine...');

  try {
    const res = await fetch('/api/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to start pipeline');

    appendLog(`Job queued: ${data.job_id}`);
    startPolling(data.job_id);
  } catch (err) {
    alert(`Pipeline error: ${err.message}`);
    btn.disabled = false;
    btn.textContent = '🚀 Run Autonomous AI Clipper';
    progContainer.classList.add('hidden');
  }
}

function updateProgress(percent, stepText, detailsText) {
  const fill = document.getElementById('pipeline-progress-fill');
  const pText = document.getElementById('progress-percent-text');
  const sText = document.getElementById('progress-step-text');
  const dText = document.getElementById('progress-details');

  fill.style.width = `${percent}%`;
  pText.textContent = `${percent}%`;
  if (stepText) sText.textContent = stepText;
  if (detailsText) dText.textContent = detailsText;
}

function startPolling(jobId) {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`/api/status/${jobId}`);
      if (!res.ok) return;
      const job = await res.json();

      updateProgress(job.progress, job.current_step, job.details);
      if (job.log) appendLog(job.log);

      if (job.status === 'completed') {
        clearInterval(pollInterval);
        document.getElementById('btn-start').disabled = false;
        document.getElementById('btn-start').textContent = '🚀 Run Autonomous AI Clipper';
        updateProgress(100, 'All clips rendered successfully!', 'Export complete.');
        appendLog(`Pipeline finished! Rendered ${job.clips.length} highlights.`);
        renderClipsShowcase(job.clips);
      } else if (job.status === 'failed') {
        clearInterval(pollInterval);
        document.getElementById('btn-start').disabled = false;
        document.getElementById('btn-start').textContent = '🚀 Run Autonomous AI Clipper';
        updateProgress(0, 'Failed', job.error || 'Unknown error');
        appendLog(`Pipeline failed: ${job.error}`);
        alert(`Pipeline failed: ${job.error}`);
      }
    } catch (err) {
      console.error('Polling error:', err);
    }
  }, 1000);
}

// Render generated clips showcase
function renderClipsShowcase(clips) {
  const container = document.getElementById('clips-showcase');
  if (!clips || clips.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🎞️</div>
        <p>No clips found.</p>
      </div>`;
    return;
  }

  container.innerHTML = '';
  clips.forEach((clip, idx) => {
    const card = document.createElement('div');
    card.className = 'clip-card';
    card.innerHTML = `
      <div class="clip-video-box">
        <video class="clip-video-player" controls preload="metadata" src="${clip.url}">
          Your browser does not support HTML5 video.
        </video>
      </div>
      <div class="clip-details">
        <h3>#${idx + 1}: ${clip.title}</h3>
        <div class="clip-meta-row">
          <span class="clip-score-badge">Virality Score: ${clip.score || 95}/100</span>
          <span>⏱️ ${clip.duration}s (${clip.start}s - ${clip.end}s)</span>
          <span>📐 ${clip.aspect_ratio || '9:16'}</span>
          <span>💾 ${clip.size_mb || '0'} MB</span>
        </div>
        <div class="clip-desc">
          <strong>Key Hook / Explanation:</strong>
          <p>${clip.explanation || clip.text || 'High pacing viral segment with synchronized speech.'}</p>
        </div>
        <div class="clip-actions">
          <a href="${clip.download_url}" download class="btn btn-primary btn-sm">⬇️ Download MP4</a>
          <button class="btn btn-secondary btn-sm" onclick="copyClipMetadata('${encodeURIComponent(JSON.stringify(clip))}')">📋 Copy Title & Description</button>
        </div>
      </div>
    `;
    container.appendChild(card);
  });
}

function copyClipMetadata(encodedClip) {
  const clip = JSON.parse(decodeURIComponent(encodedClip));
  const text = `TITLE: ${clip.title}\n\nDESCRIPTION:\n${clip.explanation || clip.text}\n\n#shorts #reels #viral #ai`;
  navigator.clipboard.writeText(text).then(() => {
    alert('Title & description copied to clipboard!');
  });
}

// Load Existing Exports
async function loadExistingExports() {
  try {
    const res = await fetch('/api/exports');
    const data = await res.json();
    renderClipsShowcase(data.clips);
  } catch (err) {
    console.error('Failed to load exports:', err);
  }
}

// Run Style Analysis
async function runStyleAnalysis() {
  const view = document.getElementById('style-report-view');
  view.innerHTML = '<p>Analyzing reference videos in <code>style/</code>...</p>';
  try {
    const res = await fetch('/api/analyze-style', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Analysis failed');
    view.innerHTML = `<pre style="white-space: pre-wrap; font-family: inherit;">${data.markdown}</pre>`;
  } catch (err) {
    view.innerHTML = `<p style="color: var(--danger)">Error: ${err.message}</p>`;
  }
}

// Initial Boot
window.addEventListener('DOMContentLoaded', () => {
  refreshRawVideos();
  loadExistingExports();
});
