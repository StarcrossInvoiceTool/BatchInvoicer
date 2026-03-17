/* Stage 1 (Data Preparation) — tab switching, file uploads, session management. */

function getCurrentTab() {
    if (!document.getElementById('section-xlsx').classList.contains('hidden')) {
        return 'xlsx';
    } else if (!document.getElementById('section-csv').classList.contains('hidden')) {
        return 'csv';
    } else if (!document.getElementById('section-merge').classList.contains('hidden')) {
        return 'merge';
    }
    return 'xlsx';
}

function switchTab(tab) {
    document.querySelectorAll('.tab-section').forEach(section => {
        section.classList.add('hidden');
    });

    document.querySelectorAll('[id^="tab-"]').forEach(btn => {
        btn.classList.remove('border-b-2', 'border-accent', 'bg-blue-50', 'text-gray-700');
        btn.classList.add('text-gray-500');
    });

    document.getElementById(`section-${tab}`).classList.remove('hidden');

    const activeTab = document.getElementById(`tab-${tab}`);
    activeTab.classList.add('border-b-2', 'border-accent', 'bg-blue-50', 'text-gray-700');
    activeTab.classList.remove('text-gray-500');

    document.getElementById('error').classList.add('hidden');

    populatePreviousFilesForTab(tab);

    restoreTabSuccessState(tab);
}

function restoreTabSuccessState(tab) {
    const successState = tabSuccessState[tab];
    if (!successState) {
        document.getElementById('success').classList.add('hidden');
        return;
    }

    const conversionType = successState.conversionType;
    const sessionId = successState.sessionId;
    const files = successState.files;
    const fileCount = successState.fileCount;

    if (conversionType === 'xlsx') {
        document.getElementById('file-count').textContent = `${fileCount} CSV file(s) created.`;
        const downloadLink = document.getElementById('download-link');
        downloadLink.href = `/api/download-conversion-zip/${sessionId}`;
        downloadLink.textContent = 'Download ZIP File';

        if (files && files.length > 0) {
            setupFileSelection(sessionId, files, 'xlsx');
        }

        const continueBtn = document.getElementById('continue-to-invoices-btn');
        continueBtn.onclick = () => {
            const currentState = {
                activeTab: getCurrentTab(),
                sessionId: sessionId,
                files: files,
                conversionType: 'xlsx',
                conversionSessionId: sessionId,
                fileCount: fileCount,
                showSuccess: true,
                allConversionSessions: allConversionSessions
            };
            sessionStorage.setItem('previousPage', JSON.stringify({
                url: window.location.href,
                state: currentState
            }));
            window.location.href = `/stage2?session_id=${sessionId}`;
        };

        document.getElementById('success').classList.remove('hidden');
        document.getElementById('upload-section-xlsx').classList.remove('hidden');

    } else if (conversionType === 'csv-division') {
        document.getElementById('file-count').textContent = `${fileCount} CSV file(s) created.`;
        const downloadLink = document.getElementById('download-link');
        downloadLink.href = `/api/download-conversion-zip/${sessionId}`;
        downloadLink.textContent = 'Download ZIP File';

        if (files && files.length > 0) {
            setupFileSelection(sessionId, files, 'csv-division');
        }

        const continueBtn = document.getElementById('continue-to-invoices-btn');
        continueBtn.onclick = () => {
            const currentState = {
                activeTab: getCurrentTab(),
                sessionId: sessionId,
                files: files,
                conversionType: 'csv-division',
                conversionSessionId: sessionId,
                fileCount: fileCount,
                showSuccess: true,
                allConversionSessions: allConversionSessions
            };
            sessionStorage.setItem('previousPage', JSON.stringify({
                url: window.location.href,
                state: currentState
            }));
            window.location.href = `/stage2?session_id=${sessionId}`;
        };

        document.getElementById('success').classList.remove('hidden');
        document.getElementById('upload-section-csv').classList.remove('hidden');

    } else if (conversionType === 'merge') {
        document.getElementById('file-count').textContent = `1 merged file (${successState.sourceCount || 0} files combined)`;
        const downloadLink = document.getElementById('download-link');
        downloadLink.href = `/api/download-conversion-zip/${sessionId}`;
        downloadLink.textContent = `Download ${successState.mergedFilename || 'merged file'}`;

        if (files && files.length > 0) {
            setupFileSelection(sessionId, files, 'merge', successState.originalSessionId);
        }

        const continueBtn = document.getElementById('continue-to-invoices-btn');
        continueBtn.onclick = () => {
            const currentState = {
                activeTab: getCurrentTab(),
                sessionId: successState.originalSessionId || null,
                files: files,
                conversionType: 'merge',
                conversionSessionId: sessionId,
                mergedFilename: successState.mergedFilename,
                showSuccess: true,
                allConversionSessions: allConversionSessions
            };
            sessionStorage.setItem('previousPage', JSON.stringify({
                url: window.location.href,
                state: currentState
            }));
            window.location.href = `/stage2?session_id=${sessionId}`;
        };

        document.getElementById('success').classList.remove('hidden');
        document.getElementById('upload-section-merge').classList.remove('hidden');
    }
}

function populateDivisionFilesList() {
    const filesList = document.getElementById('division-files-list');
    filesList.innerHTML = '';

    lastConversionFiles.forEach((filename, index) => {
        const fileItem = document.createElement('div');
        fileItem.className = 'flex items-center gap-2 p-2 bg-white border border-gray-200 rounded';
        fileItem.innerHTML = `
            <input
                type="checkbox"
                class="division-file-checkbox"
                data-filename="${filename}"
                id="file-${index}"
                checked
            >
            <label for="file-${index}" class="flex-1 text-sm text-gray-700 cursor-pointer">
                ${filename}
            </label>
        `;
        filesList.appendChild(fileItem);
    });

    document.getElementById('previous-division-section').classList.remove('hidden');
}

document.getElementById('use-division-files-btn').addEventListener('click', async () => {
    const selectedCheckboxes = document.querySelectorAll('.division-file-checkbox:checked');

    if (selectedCheckboxes.length === 0) {
        showError('Please select at least one file to merge');
        return;
    }

    const selectedFiles = Array.from(selectedCheckboxes).map(cb => cb.getAttribute('data-filename'));
    const filenameInput = document.getElementById('merged_filename');

    const filesBySession = {};
    selectedCheckboxes.forEach(cb => {
        const filename = cb.getAttribute('data-filename');
        const fileSessionId = cb.getAttribute('data-session-id');
        if (!filesBySession[fileSessionId]) {
            filesBySession[fileSessionId] = [];
        }
        filesBySession[fileSessionId].push(filename);
    });

    document.getElementById('upload-section-merge').classList.add('hidden');
    document.getElementById('previous-division-section').classList.add('hidden');
    document.getElementById('loading').classList.remove('hidden');
    document.getElementById('error').classList.add('hidden');
    document.getElementById('success').classList.add('hidden');

    try {
        const sessionIds = Object.keys(filesBySession);
        let response;

        if (sessionIds.length === 1) {
            const formData = new FormData();
            formData.append('session_id', sessionIds[0]);
            formData.append('files', JSON.stringify(selectedFiles));
            if (filenameInput.value.trim()) {
                formData.append('filename', filenameInput.value.trim());
            }

            response = await fetch('/api/merge-csvs-from-session', {
                method: 'POST',
                body: formData
            });
        } else {
            showError('Files from multiple sessions cannot be merged directly. Please merge files from the same session.');
            document.getElementById('loading').classList.add('hidden');
            document.getElementById('upload-section-merge').classList.remove('hidden');
            document.getElementById('previous-division-section').classList.remove('hidden');
            return;
        }

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Merge failed');
        }

        const data = await response.json();
        const sessionId = data.session_id;
        const mergedFilename = data.filename;

        const allPreviousFiles = getAllAvailableFiles();
        let allAvailableFiles = [mergedFilename];
        allPreviousFiles.forEach(file => {
            if (!allAvailableFiles.includes(file.filename)) {
                allAvailableFiles.push(file.filename);
            }
        });

        addConversionSession(sessionId, 'merge', [mergedFilename], {
            mergedFilename: mergedFilename,
            sourceCount: selectedFiles.length
        });

        document.getElementById('file-count').textContent = `1 merged file (${selectedFiles.length} files combined)`;

        const downloadLink = document.getElementById('download-link');
        downloadLink.href = `/api/download-conversion-zip/${sessionId}`;
        downloadLink.textContent = `Download ${mergedFilename}`;

        const firstSelectedSessionId = selectedCheckboxes[0]?.getAttribute('data-session-id') || null;
        setupFileSelection(sessionId, allAvailableFiles, 'merge', firstSelectedSessionId);

        const continueBtn = document.getElementById('continue-to-invoices-btn');
        continueBtn.onclick = () => {
            const currentState = {
                activeTab: getCurrentTab(),
                sessionId: lastConversionSessionId,
                files: lastConversionFiles,
                conversionType: 'merge',
                conversionSessionId: sessionId,
                mergedFilename: mergedFilename,
                showSuccess: true,
                allConversionSessions: allConversionSessions
            };
            sessionStorage.setItem('previousPage', JSON.stringify({
                url: window.location.href,
                state: currentState
            }));
            window.location.href = `/stage2?session_id=${sessionId}`;
        };

        tabSuccessState['merge'] = {
            conversionType: 'merge',
            sessionId: sessionId,
            files: allAvailableFiles,
            mergedFilename: mergedFilename,
            sourceCount: selectedFiles.length,
            originalSessionId: firstSelectedSessionId
        };

        document.getElementById('loading').classList.add('hidden');
        document.getElementById('success').classList.remove('hidden');
        document.getElementById('upload-section-merge').classList.remove('hidden');
        document.getElementById('previous-division-section').classList.remove('hidden');

    } catch (error) {
        document.getElementById('loading').classList.add('hidden');
        document.getElementById('upload-section-merge').classList.remove('hidden');
        document.getElementById('previous-division-section').classList.remove('hidden');
        showError(error.message);
    }
});

document.getElementById('upload-form-merge').addEventListener('submit', async (e) => {
    e.preventDefault();

    const formData = new FormData();
    const fileInput = document.getElementById('merge_csv_files');
    const filenameInput = document.getElementById('merged_filename');

    if (!fileInput.files || fileInput.files.length === 0) {
        showError('Please select at least one CSV file to upload, or use files from previous division above');
        return;
    }

    for (let i = 0; i < fileInput.files.length; i++) {
        formData.append('files', fileInput.files[i]);
    }

    if (filenameInput.value.trim()) {
        formData.append('filename', filenameInput.value.trim());
    }

    document.getElementById('upload-section-merge').classList.add('hidden');
    document.getElementById('loading').classList.remove('hidden');
    document.getElementById('error').classList.add('hidden');
    document.getElementById('success').classList.add('hidden');

    try {
        const response = await fetch('/api/merge-csvs', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Merge failed');
        }

        const data = await response.json();
        const sessionId = data.session_id;
        const mergedFilename = data.filename;

        const allPreviousFiles = getAllAvailableFiles();
        let allAvailableFiles = [mergedFilename];
        allPreviousFiles.forEach(file => {
            if (!allAvailableFiles.includes(file.filename)) {
                allAvailableFiles.push(file.filename);
            }
        });

        addConversionSession(sessionId, 'merge', [mergedFilename], {
            mergedFilename: mergedFilename,
            sourceCount: fileInput.files.length
        });

        document.getElementById('file-count').textContent = `1 merged file (${fileInput.files.length} files combined)`;

        const downloadLink = document.getElementById('download-link');
        downloadLink.href = `/api/download-conversion-zip/${sessionId}`;
        downloadLink.textContent = `Download ${mergedFilename}`;

        setupFileSelection(sessionId, allAvailableFiles, 'merge');

        const continueBtn = document.getElementById('continue-to-invoices-btn');
        continueBtn.onclick = () => {
            const currentState = {
                activeTab: getCurrentTab(),
                sessionId: lastConversionSessionId,
                files: lastConversionFiles,
                conversionType: 'merge',
                conversionSessionId: sessionId,
                mergedFilename: mergedFilename,
                showSuccess: true
            };
            sessionStorage.setItem('previousPage', JSON.stringify({
                url: window.location.href,
                state: currentState
            }));
            window.location.href = `/stage2?session_id=${sessionId}`;
        };

        tabSuccessState['merge'] = {
            conversionType: 'merge',
            sessionId: sessionId,
            files: allAvailableFiles,
            mergedFilename: mergedFilename,
            sourceCount: fileInput.files.length,
            originalSessionId: null
        };

        document.getElementById('loading').classList.add('hidden');
        document.getElementById('success').classList.remove('hidden');
        document.getElementById('upload-section-merge').classList.remove('hidden');

    } catch (error) {
        document.getElementById('loading').classList.add('hidden');
        document.getElementById('upload-section-merge').classList.remove('hidden');
        showError(error.message);
    }
});

document.getElementById('upload-form-xlsx').addEventListener('submit', async (e) => {
    e.preventDefault();

    const formData = new FormData();
    const fileInput = document.getElementById('xlsx_file');
    const file = fileInput.files[0];

    if (!file) {
        showError('Please select a file');
        return;
    }

    formData.append('file', file);

    document.getElementById('upload-section-xlsx').classList.add('hidden');
    document.getElementById('loading').classList.remove('hidden');
    document.getElementById('error').classList.add('hidden');
    document.getElementById('success').classList.add('hidden');

    try {
        const response = await fetch('/api/convert-xlsx', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Conversion failed');
        }

        const data = await response.json();
        const sessionId = data.session_id;
        const fileCount = data.file_count;
        const files = data.files || [];

        addConversionSession(sessionId, 'xlsx', files, {
            fileCount: fileCount
        });

        document.getElementById('file-count').textContent = `${fileCount} CSV file(s) created.`;

        lastConversionSessionId = sessionId;
        lastConversionFiles = files;

        const downloadLink = document.getElementById('download-link');
        downloadLink.href = `/api/download-conversion-zip/${sessionId}`;
        downloadLink.textContent = 'Download ZIP File';

        setupFileSelection(sessionId, files, 'xlsx');

        const continueBtn = document.getElementById('continue-to-invoices-btn');
        continueBtn.onclick = () => {
            const currentState = {
                activeTab: getCurrentTab(),
                sessionId: sessionId,
                files: files,
                conversionType: 'xlsx',
                conversionSessionId: sessionId,
                fileCount: fileCount,
                showSuccess: true,
                allConversionSessions: allConversionSessions
            };
            sessionStorage.setItem('previousPage', JSON.stringify({
                url: window.location.href,
                state: currentState
            }));
            window.location.href = `/stage2?session_id=${sessionId}`;
        };

        tabSuccessState['xlsx'] = {
            conversionType: 'xlsx',
            sessionId: sessionId,
            files: files,
            fileCount: fileCount
        };

        document.getElementById('loading').classList.add('hidden');
        document.getElementById('success').classList.remove('hidden');
        document.getElementById('upload-section-xlsx').classList.remove('hidden');

    } catch (error) {
        document.getElementById('loading').classList.add('hidden');
        document.getElementById('upload-section-xlsx').classList.remove('hidden');
        showError(error.message);
    }
});

document.getElementById('upload-form-csv').addEventListener('submit', async (e) => {
    e.preventDefault();

    const formData = new FormData();
    const fileInput = document.getElementById('csv_file');
    const file = fileInput.files[0];

    if (!file) {
        showError('Please select a file');
        return;
    }

    formData.append('file', file);

    document.getElementById('upload-section-csv').classList.add('hidden');
    document.getElementById('loading').classList.remove('hidden');
    document.getElementById('error').classList.add('hidden');
    document.getElementById('success').classList.add('hidden');

    try {
        const response = await fetch('/api/convert-csv', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Conversion failed');
        }

        const data = await response.json();
        const sessionId = data.session_id;
        const fileCount = data.file_count;
        const files = data.files || [];

        lastConversionSessionId = sessionId;
        lastConversionFiles = files;

        addConversionSession(sessionId, 'csv-division', files, {
            fileCount: fileCount
        });

        document.getElementById('file-count').textContent = `${fileCount} CSV file(s) created.`;

        const downloadLink = document.getElementById('download-link');
        downloadLink.href = `/api/download-conversion-zip/${sessionId}`;
        downloadLink.textContent = 'Download ZIP File';

        setupFileSelection(sessionId, files, 'csv-division');

        const continueBtn = document.getElementById('continue-to-invoices-btn');
        continueBtn.onclick = () => {
            const currentState = {
                activeTab: getCurrentTab(),
                sessionId: sessionId,
                files: files,
                conversionType: 'csv-division',
                conversionSessionId: sessionId,
                fileCount: fileCount,
                showSuccess: true,
                allConversionSessions: allConversionSessions
            };
            sessionStorage.setItem('previousPage', JSON.stringify({
                url: window.location.href,
                state: currentState
            }));
            window.location.href = `/stage2?session_id=${sessionId}`;
        };

        tabSuccessState['csv'] = {
            conversionType: 'csv-division',
            sessionId: sessionId,
            files: files,
            fileCount: fileCount
        };

        document.getElementById('loading').classList.add('hidden');
        document.getElementById('success').classList.remove('hidden');
        document.getElementById('upload-section-csv').classList.remove('hidden');

    } catch (error) {
        document.getElementById('loading').classList.add('hidden');
        document.getElementById('upload-section-csv').classList.remove('hidden');
        showError(error.message);
    }
});

let lastConversionSessionId = null;
let lastConversionFiles = [];
let allConversionSessions = {};
let tabSuccessState = {};

(() => {
    const restoreStateData = sessionStorage.getItem('restoreState');
    if (!restoreStateData) {
        sessionStorage.removeItem('allConversionSessions');
        allConversionSessions = {};
        lastConversionSessionId = null;
        lastConversionFiles = [];
    }
})();

function saveConversionSessions() {
    sessionStorage.setItem('allConversionSessions', JSON.stringify(allConversionSessions));
}

function addConversionSession(sessionId, type, files, metadata = {}) {
    allConversionSessions[sessionId] = {
        type: type,
        files: files,
        sessionId: sessionId,
        ...metadata
    };
    saveConversionSessions();
}

function getAllAvailableFiles() {
    const allFiles = [];
    for (const sessionId in allConversionSessions) {
        const session = allConversionSessions[sessionId];
        session.files.forEach(filename => {
            allFiles.push({
                filename: filename,
                sessionId: sessionId,
                type: session.type
            });
        });
    }
    return allFiles;
}

async function populatePreviousFilesForTab(tab) {
    const allFiles = getAllAvailableFiles();

    if (tab === 'merge') {
        const filesList = document.getElementById('division-files-list');
        filesList.innerHTML = '';

        if (allFiles.length === 0) {
            document.getElementById('previous-division-section').classList.add('hidden');
            return;
        }

        const filesBySession = {};
        allFiles.forEach(file => {
            if (!filesBySession[file.sessionId]) {
                filesBySession[file.sessionId] = [];
            }
            filesBySession[file.sessionId].push(file);
        });

        for (const sessionId in filesBySession) {
            const session = allConversionSessions[sessionId];
            const sessionFiles = filesBySession[sessionId];

            const sessionHeader = document.createElement('div');
            sessionHeader.className = 'mb-2 mt-3 first:mt-0';
            const typeLabel = session.type === 'xlsx' ? 'XLSX Conversion' :
                             session.type === 'csv-division' ? 'CSV Division' :
                             session.type === 'merge' ? 'Merged File' : 'Previous Conversion';
            sessionHeader.innerHTML = `<p class="text-xs font-semibold text-gray-600">${typeLabel}</p>`;
            filesList.appendChild(sessionHeader);

            sessionFiles.forEach((file, index) => {
                const fileItem = document.createElement('div');
                fileItem.className = 'flex items-center gap-2 p-2 bg-white border border-gray-200 rounded';
                fileItem.innerHTML = `
                    <input
                        type="checkbox"
                        class="division-file-checkbox"
                        data-filename="${file.filename}"
                        data-session-id="${file.sessionId}"
                        id="file-${sessionId}-${index}"
                        checked
                    >
                    <label for="file-${sessionId}-${index}" class="flex-1 text-sm text-gray-700 cursor-pointer">
                        ${file.filename}
                    </label>
                `;
                filesList.appendChild(fileItem);
            });
        }

        document.getElementById('previous-division-section').classList.remove('hidden');

    } else if (tab === 'csv') {
        const uploadSection = document.getElementById('upload-section-csv');

        let previousFilesSection = document.getElementById('previous-files-section-csv');
        if (!previousFilesSection) {
            previousFilesSection = document.createElement('div');
            previousFilesSection.id = 'previous-files-section-csv';
            previousFilesSection.className = 'mb-6';
            uploadSection.parentNode.insertBefore(previousFilesSection, uploadSection);
        }

        if (allFiles.length === 0) {
            previousFilesSection.classList.add('hidden');
        } else {
            previousFilesSection.classList.remove('hidden');
            previousFilesSection.innerHTML = `
                <div class="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
                    <h3 class="text-sm font-semibold text-gray-800 mb-2">Files from Previous Conversions</h3>
                    <p class="text-xs text-gray-600 mb-3">Select a file from previous conversions to split:</p>
                    <div id="previous-files-list-csv" class="space-y-2 max-h-60 overflow-y-auto mb-3">
                    </div>
                    <div class="text-center mb-2">
                        <span class="text-sm text-gray-500">OR</span>
                    </div>
                </div>
            `;

            const filesList = document.getElementById('previous-files-list-csv');
            filesList.innerHTML = '';

            const filesBySession = {};
            allFiles.forEach(file => {
                if (!filesBySession[file.sessionId]) {
                    filesBySession[file.sessionId] = [];
                }
                filesBySession[file.sessionId].push(file);
            });

            for (const sessionId in filesBySession) {
                const sessionFiles = filesBySession[sessionId];

                sessionFiles.forEach((file, index) => {
                    const fileItem = document.createElement('div');
                    fileItem.className = 'flex items-center gap-2 p-2 bg-white border border-gray-200 rounded';
                    fileItem.innerHTML = `
                        <input
                            type="radio"
                            name="previous-file-csv"
                            class="previous-file-radio-csv"
                            data-filename="${file.filename}"
                            data-session-id="${file.sessionId}"
                            id="prev-file-${sessionId}-${index}"
                        >
                        <label for="prev-file-${sessionId}-${index}" class="flex-1 text-sm text-gray-700 cursor-pointer">
                            ${file.filename}
                        </label>
                    `;
                    filesList.appendChild(fileItem);
                });
            }

            const useFileBtn = document.createElement('button');
            useFileBtn.id = 'use-previous-file-csv-btn';
            useFileBtn.className = 'w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded transition duration-200';
            useFileBtn.textContent = 'Use Selected File';
            useFileBtn.onclick = async () => {
                const selectedRadio = document.querySelector('input[name="previous-file-csv"]:checked');
                if (!selectedRadio) {
                    showError('Please select a file to use');
                    return;
                }

                const filename = selectedRadio.getAttribute('data-filename');
                const fileSessionId = selectedRadio.getAttribute('data-session-id');

                try {
                    const fileResponse = await fetch(`/api/download-conversion-file/${fileSessionId}/${encodeURIComponent(filename)}`);
                    if (!fileResponse.ok) {
                        throw new Error('Failed to download file from session');
                    }

                    const blob = await fileResponse.blob();
                    const file = new File([blob], filename, { type: 'text/csv' });

                    const dataTransfer = new DataTransfer();
                    dataTransfer.items.add(file);
                    document.getElementById('csv_file').files = dataTransfer.files;

                    document.getElementById('upload-form-csv').dispatchEvent(new Event('submit', { cancelable: true }));

                } catch (error) {
                    showError(error.message || 'Failed to load file from previous conversion');
                }
            };
            previousFilesSection.querySelector('.bg-blue-50').appendChild(useFileBtn);
        }
    }
}

function setupFileSelection(sessionId, files, sourceType, originalSessionId = null) {
    if (sourceType !== 'csv-division' && sourceType !== 'merge' && sourceType !== 'xlsx') {
        return;
    }

    const fileSelectionSection = document.getElementById('file-selection-section');
    const fileSelectionList = document.getElementById('file-selection-list');
    fileSelectionList.innerHTML = '';

    files.forEach((filename, index) => {
        const fileItem = document.createElement('div');
        fileItem.className = 'flex items-center gap-2 p-2 hover:bg-gray-50 rounded';

        let fileSessionId = sessionId;
        if (sourceType === 'merge' && originalSessionId && index < files.length - 1) {
            fileSessionId = originalSessionId;
        }

        fileItem.innerHTML = `
            <input
                type="checkbox"
                class="file-selection-checkbox"
                data-filename="${filename}"
                data-session-id="${fileSessionId}"
                id="select-file-${index}"
                checked
            >
            <label for="select-file-${index}" class="flex-1 text-sm text-gray-700 cursor-pointer">
                ${filename}
            </label>
        `;
        fileSelectionList.appendChild(fileItem);
    });

    const continueWithSelectedBtn = document.getElementById('continue-with-selected-btn');
    continueWithSelectedBtn.onclick = async () => {
        const selectedCheckboxes = document.querySelectorAll('.file-selection-checkbox:checked');

        if (selectedCheckboxes.length === 0) {
            showError('Please select at least one file to continue');
            return;
        }

        const filesBySession = {};
        selectedCheckboxes.forEach(cb => {
            const filename = cb.getAttribute('data-filename');
            const fileSessionId = cb.getAttribute('data-session-id') || sessionId;
            if (!filesBySession[fileSessionId]) {
                filesBySession[fileSessionId] = [];
            }
            filesBySession[fileSessionId].push(filename);
        });

        const currentTab = getCurrentTab();
        const successDiv = document.getElementById('success');
        const fileCountText = document.getElementById('file-count').textContent;
        const downloadLink = document.getElementById('download-link');

        let currentState = {
            activeTab: currentTab,
            sessionId: originalSessionId || null,
            files: files,
            showSuccess: !successDiv.classList.contains('hidden'),
            conversionType: sourceType,
            conversionSessionId: sessionId,
            allConversionSessions: allConversionSessions
        };

        if (sourceType === 'csv-division') {
            const countMatch = fileCountText.match(/(\d+)\s+CSV file/);
            if (countMatch) {
                currentState.fileCount = parseInt(countMatch[1]);
            }
        } else if (sourceType === 'merge') {
            currentState.mergedFilename = downloadLink.textContent.replace('Download ', '');
        }

        sessionStorage.setItem('previousPage', JSON.stringify({
            url: window.location.href,
            state: currentState
        }));

        const sessionIds = Object.keys(filesBySession);
        if (sessionIds.length === 1) {
            const singleSessionId = sessionIds[0];
            const selectedFiles = filesBySession[singleSessionId];

            const filesParam = encodeURIComponent(JSON.stringify(selectedFiles));
            window.location.href = `/stage2?session_id=${singleSessionId}&files=${filesParam}`;
        } else {
            try {
                const formData = new FormData();
                formData.append('files_data', JSON.stringify(filesBySession));

                const response = await fetch('/api/create-combined-session', {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Failed to create combined session');
                }

                const data = await response.json();
                window.location.href = `/stage2?session_id=${data.session_id}`;
            } catch (error) {
                showError(`Failed to combine files: ${error.message}`);
            }
        }
    };

    fileSelectionSection.classList.remove('hidden');
}

function showError(message) {
    const errorDiv = document.getElementById('error');
    errorDiv.querySelector('p').textContent = message;
    errorDiv.classList.remove('hidden');
}

(() => {
    const restoreStateData = sessionStorage.getItem('restoreState');
    if (restoreStateData) {
        try {
            const state = JSON.parse(restoreStateData);

            if (state.sessionId) {
                lastConversionSessionId = state.sessionId;
            }
            if (state.files) {
                lastConversionFiles = state.files;
            }

            if (state.allConversionSessions) {
                allConversionSessions = state.allConversionSessions;
                saveConversionSessions();
            }

            if (state.activeTab) {
                switchTab(state.activeTab);
            }

            if (state.showSuccess && state.conversionType) {
                if (state.conversionType === 'csv-division') {
                    tabSuccessState['csv'] = {
                        conversionType: 'csv-division',
                        sessionId: state.conversionSessionId,
                        files: state.files,
                        fileCount: state.fileCount
                    };

                    document.getElementById('file-count').textContent = `${state.fileCount} CSV file(s) created.`;
                    const downloadLink = document.getElementById('download-link');
                    downloadLink.href = `/api/download-conversion-zip/${state.conversionSessionId}`;
                    downloadLink.textContent = 'Download ZIP File';

                    if (state.files && state.files.length > 0) {
                        setupFileSelection(state.conversionSessionId, state.files, 'csv-division');
                    }

                    const continueBtn = document.getElementById('continue-to-invoices-btn');
                    continueBtn.onclick = () => {
                        const currentState = {
                            activeTab: getCurrentTab(),
                            sessionId: state.sessionId,
                            files: state.files,
                            conversionType: 'csv-division',
                            conversionSessionId: state.conversionSessionId,
                            fileCount: state.fileCount,
                            showSuccess: true,
                            allConversionSessions: allConversionSessions
                        };
                        sessionStorage.setItem('previousPage', JSON.stringify({
                            url: window.location.href,
                            state: currentState
                        }));
                        window.location.href = `/stage2?session_id=${state.conversionSessionId}`;
                    };

                    document.getElementById('success').classList.remove('hidden');
                    document.getElementById('upload-section-csv').classList.remove('hidden');

                } else if (state.conversionType === 'merge') {
                    tabSuccessState['merge'] = {
                        conversionType: 'merge',
                        sessionId: state.conversionSessionId,
                        files: state.files,
                        mergedFilename: state.mergedFilename,
                        sourceCount: state.files ? state.files.length : 0,
                        originalSessionId: state.sessionId
                    };

                    document.getElementById('file-count').textContent = `1 merged file created.`;
                    const downloadLink = document.getElementById('download-link');
                    downloadLink.href = `/api/download-conversion-zip/${state.conversionSessionId}`;
                    downloadLink.textContent = `Download ${state.mergedFilename || 'merged file'}`;

                    if (state.files && state.files.length > 0) {
                        setupFileSelection(state.conversionSessionId, state.files, 'merge', state.sessionId);
                    }

                    const continueBtn = document.getElementById('continue-to-invoices-btn');
                    continueBtn.onclick = () => {
                        const currentState = {
                            activeTab: getCurrentTab(),
                            sessionId: state.sessionId || null,
                            files: state.files,
                            conversionType: 'merge',
                            conversionSessionId: state.conversionSessionId,
                            mergedFilename: state.mergedFilename,
                            showSuccess: true,
                            allConversionSessions: allConversionSessions
                        };
                        sessionStorage.setItem('previousPage', JSON.stringify({
                            url: window.location.href,
                            state: currentState
                        }));
                        window.location.href = `/stage2?session_id=${state.conversionSessionId}`;
                    };

                    document.getElementById('success').classList.remove('hidden');
                    document.getElementById('upload-section-merge').classList.remove('hidden');

                    if (state.sessionId && state.files && state.files.length > 1) {
                        populateDivisionFilesList();
                        document.getElementById('previous-division-section').classList.remove('hidden');
                    }

                } else if (state.conversionType === 'xlsx') {
                    tabSuccessState['xlsx'] = {
                        conversionType: 'xlsx',
                        sessionId: state.conversionSessionId,
                        files: state.files,
                        fileCount: state.fileCount
                    };

                    document.getElementById('file-count').textContent = `${state.fileCount} CSV file(s) created.`;
                    const downloadLink = document.getElementById('download-link');
                    downloadLink.href = `/api/download-conversion-zip/${state.conversionSessionId}`;
                    downloadLink.textContent = 'Download ZIP File';

                    if (state.files && state.files.length > 0) {
                        setupFileSelection(state.conversionSessionId, state.files, 'xlsx');
                    }

                    const continueBtn = document.getElementById('continue-to-invoices-btn');
                    continueBtn.onclick = () => {
                        const currentState = {
                            activeTab: getCurrentTab(),
                            sessionId: state.sessionId,
                            files: state.files,
                            conversionType: 'xlsx',
                            conversionSessionId: state.conversionSessionId,
                            fileCount: state.fileCount,
                            showSuccess: true,
                            allConversionSessions: allConversionSessions
                        };
                        sessionStorage.setItem('previousPage', JSON.stringify({
                            url: window.location.href,
                            state: currentState
                        }));
                        window.location.href = `/stage2?session_id=${state.conversionSessionId}`;
                    };

                    document.getElementById('success').classList.remove('hidden');
                    document.getElementById('upload-section-xlsx').classList.remove('hidden');
                }
            }

            sessionStorage.removeItem('restoreState');
        } catch (e) {
            console.error('Failed to restore state:', e);
        }
    }
})();
