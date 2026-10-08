const THREAD_KEY = 'cloudops_sentinel_thread_id';

function newThreadId() {
  return 'incident-' + crypto.randomUUID();
}

let threadId =
  localStorage.getItem(THREAD_KEY) || newThreadId();

localStorage.setItem(THREAD_KEY, threadId);


// ============================================================
// DOM REFERENCES
// ============================================================

const q = document.getElementById('question');
const send = document.getElementById('sendBtn');
const messages = document.getElementById('messages');

const upload = document.getElementById('uploadBtn');
const fileInput = document.getElementById('fileInput');
const uploadStatus = document.getElementById('uploadStatus');
const fileLabel = document.getElementById('fileLabel');

const starters = document.getElementById('starterPrompts');

const sessionId = document.getElementById('sessionId');
const newSessionBtn = document.getElementById('newSessionBtn');


// ============================================================
// SESSION
// ============================================================

function renderSession() {
  if (sessionId) {
    sessionId.textContent =
      'MEMORY / ' + threadId.slice(-8).toUpperCase();
  }
}

renderSession();


// ============================================================
// HELPERS
// ============================================================

function esc(value = '') {
  return String(value).replace(
    /[&<>"']/g,
    character => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    })[character]
  );
}


function pretty(value = '') {
  return String(value)
    .replaceAll('_', ' ')
    .replace(/\b\w/g, match => match.toUpperCase());
}


function addMessage(role, html, meta = '') {

  const element = document.createElement('div');

  element.className = `message ${role}`;

  const avatar =
    role === 'assistant'
      ? '<div class="avatar">S</div>'
      : '';

  const label =
    role === 'assistant'
      ? 'CLOUDOPS SENTINEL'
      : 'ON-CALL ENGINEER';

  element.innerHTML = `
    ${avatar}

    <div class="message-body">

      <div class="message-label">
        ${label}
      </div>

      <div class="bubble">
        ${html}
      </div>

      ${meta}

    </div>
  `;

  messages.appendChild(element);

  messages.scrollTop = messages.scrollHeight;

  return element;
}


function loadingMarkup() {

  return `
    <span class="thinking">
      Running Self-RAG
      <i></i>
      <i></i>
      <i></i>
    </span>
  `;
}


// ============================================================
// CHAT
// ============================================================

async function ask() {

  const question = q.value.trim();

  if (!question) {
    return;
  }

  starters.style.display = 'none';

  addMessage(
    'user',
    esc(question)
  );

  q.value = '';

  send.disabled = true;

  const loading = addMessage(
    'assistant',
    loadingMarkup()
  );


  try {

    const response = await fetch(
      '/api/chat',
      {
        method: 'POST',

        headers: {
          'Content-Type': 'application/json'
        },

        body: JSON.stringify({
          question: question,
          thread_id: threadId
        })
      }
    );


    const data = await response.json();


    if (!response.ok) {

      throw new Error(
        data.detail || 'Request failed'
      );

    }


    loading.remove();


    // ========================================================
    // RESPONSE METADATA
    // ========================================================

    let meta = `
      <div class="meta-card">

        <div class="verification">

          <span class="tag">
            ROUTE · ${esc(data.route || 'unknown')}
          </span>
    `;


    if (data.support_status) {

      meta += `
        <span class="tag ok">
          IsSUP · ${esc(
            pretty(data.support_status)
          )}
        </span>
      `;

    }


    if (data.usefulness) {

      meta += `
        <span class="tag ok">
          IsUSE · ${esc(
            pretty(data.usefulness)
          )}
        </span>
      `;

    }


    if (data.used_web_search) {

      meta += `
        <span class="tag web">
          INTERNET SEARCH USED
        </span>
      `;

    }


    // PostgreSQL instead of SQLite

    meta += `
        <span class="tag memory">
          POSTGRESQL MEMORY ·
          ${data.memory_turns || 0}
          TURN${(data.memory_turns || 0) === 1 ? '' : 'S'}
        </span>

      </div>
    `;


    // ========================================================
    // SOURCES
    // ========================================================

    if (
      Array.isArray(data.sources) &&
      data.sources.length
    ) {

      meta += `
        <div class="sources">
      `;


      meta += data.sources
        .map(source => {

          const isWeb =
            source.type === 'web';

          const icon =
            isWeb ? '⌁' : '▱';

          const sourceTitle =
            source.title ||
            source.source ||
            'Evidence';


          let sourceLink = '';

          if (source.url) {

            sourceLink = `
              ·
              <a
                target="_blank"
                rel="noopener noreferrer"
                href="${esc(source.url)}"
              >
                open source ↗
              </a>
            `;

          }


          const page =
            source.page
              ? ` · p.${esc(source.page)}`
              : '';


          return `
            <div class="source">

              <span class="source-icon">
                ${icon}
              </span>

              <span class="${isWeb ? 'tag web' : 'tag internal'}">
                ${isWeb ? 'WEB' : 'INTERNAL'}
              </span>

              <span>
                ${esc(sourceTitle)}
                ${page}
                ${sourceLink}
              </span>

            </div>
          `;

        })
        .join('');


      meta += `
        </div>
      `;

    }


    // ========================================================
    // SELF-RAG TRACE
    // ========================================================

    if (
      Array.isArray(data.trace) &&
      data.trace.length
    ) {

      meta += `
        <div class="trace">

          <details>

            <summary>
              Inspect Self-RAG workflow trace
            </summary>

            <ol>
              ${data.trace
                .map(step => `<li>${esc(step)}</li>`)
                .join('')}
            </ol>

          </details>

        </div>
      `;

    }


    meta += `
      </div>
    `;


    addMessage(
      'assistant',
      esc(data.answer || 'No answer returned.'),
      meta
    );


  } catch (error) {

    loading.remove();

    addMessage(
      'assistant',
      `
        <span style="color:var(--danger)">
          Request failed:
          ${esc(error.message)}
        </span>
      `
    );

  } finally {

    send.disabled = false;

    q.focus();

  }
}


// ============================================================
// CHAT EVENTS
// ============================================================

send.addEventListener(
  'click',
  ask
);


q.addEventListener(
  'keydown',
  event => {

    if (
      event.key === 'Enter' &&
      !event.shiftKey
    ) {

      event.preventDefault();

      ask();

    }

  }
);


// ============================================================
// STARTER PROMPTS
// ============================================================

starters.addEventListener(
  'click',
  event => {

    const button =
      event.target.closest(
        'button[data-q]'
      );

    if (!button) {
      return;
    }

    q.value =
      button.dataset.q;

    q.focus();

  }
);


// ============================================================
// FILE SELECTION
// ============================================================

fileInput.addEventListener(
  'change',
  () => {

    const file =
      fileInput.files[0];

    fileLabel.textContent =
      file?.name ||
      'Choose runbook';

    uploadStatus.textContent = '';

    uploadStatus.className =
      'status';

  }
);


// ============================================================
// DOCUMENT UPLOAD
// ============================================================

upload.addEventListener(
  'click',
  async () => {

    const file =
      fileInput.files[0];


    if (!file) {

      uploadStatus.textContent =
        'Choose a runbook first.';

      uploadStatus.className =
        'status error';

      return;

    }


    upload.disabled = true;

    uploadStatus.textContent =
      'Indexing private operational knowledge…';

    uploadStatus.className =
      'status';


    try {

      const formData =
        new FormData();

      formData.append(
        'file',
        file
      );


      const response =
        await fetch(
          '/api/upload',
          {
            method: 'POST',
            body: formData
          }
        );


      const data =
        await response.json();


      if (!response.ok) {

        throw new Error(
          data.detail ||
          'Upload failed'
        );

      }


      uploadStatus.textContent =
        `✓ ${data.chunks_indexed} chunks indexed in ${data.namespace}`;

      uploadStatus.className =
        'status success';


      // Reset selected file.

      fileInput.value = '';

      fileLabel.textContent =
        'Choose runbook';


    } catch (error) {

      uploadStatus.textContent =
        'Error: ' +
        error.message;

      uploadStatus.className =
        'status error';

    } finally {

      upload.disabled = false;

    }

  }
);


// ============================================================
// NEW INCIDENT SESSION
// ============================================================

newSessionBtn?.addEventListener(
  'click',
  () => {

    threadId =
      newThreadId();

    localStorage.setItem(
      THREAD_KEY,
      threadId
    );

    renderSession();


    messages.innerHTML = `
      <div class="message assistant">

        <div class="avatar">
          S
        </div>

        <div class="message-body">

          <div class="message-label">
            CLOUDOPS SENTINEL
          </div>

          <div class="bubble intro">
            New incident memory session started.
            Describe the production issue and I’ll
            build context across your follow-up questions.
          </div>

        </div>

      </div>
    `;


    starters.style.display =
      'flex';

    q.value = '';

    q.focus();

  }
);