/* Stage 2 (Invoice Creation) — batch processing, summary template, navigation. */

let batchSessionId = null;
let allInvoices = [];
let currentInvoiceIndex = 0;
let summaryTemplateColumns = [];

function updateGrandTotal() {
    const selectedStyle = document.querySelector('input[name="invoice-style"]:checked');
    if (!selectedStyle) return;

    const style = selectedStyle.value;
    if (style === 'style1' || style === 'style2') {
        const selectedCheckboxes = document.querySelectorAll('.item-checkbox:checked');
        let sum = 0;

        selectedCheckboxes.forEach(checkbox => {
            const index = checkbox.getAttribute('data-index');
            const totalInput = document.querySelector(`.item-total[data-index="${index}"]`);
            if (totalInput) {
                const itemTotal = parseFloat(totalInput.value) || 0;
                if (itemTotal > 0) {
                    sum += itemTotal;
                }
            }
        });

        const netField = document.getElementById('net');
        if (netField) {
            if (style === 'style1' || (style === 'style2' && sum > 0)) {
                netField.value = sum.toFixed(2);
            }
        }

        calculateSubtotalAndVAT();
    }
}

(async () => {
    const urlParams = new URLSearchParams(window.location.search);
    const conversionSessionId = urlParams.get('session_id');
    const selectedFilesParam = urlParams.get('files');

    if (conversionSessionId) {
        document.getElementById('upload-section').classList.add('hidden');
        document.getElementById('loading').classList.remove('hidden');
        document.getElementById('error').classList.add('hidden');

        try {
            let apiUrl = `/api/get-conversion-files/${conversionSessionId}`;
            if (selectedFilesParam) {
                apiUrl += `?files=${encodeURIComponent(selectedFilesParam)}`;
            }

            const response = await fetch(apiUrl);

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Failed to load files' }));
                throw new Error(errorData.detail || `Failed to load files: ${response.status} ${response.statusText}`);
            }

            const data = await response.json();

            if (!data.invoices || data.invoices.length === 0) {
                throw new Error('No invoices found in conversion session');
            }

            batchSessionId = data.batch_session_id;
            allInvoices = data.invoices;
            currentInvoiceIndex = 0;

            populateInvoiceList(data.invoices);

            if (data.invoices.length > 0) {
                loadInvoice(data.invoices[0]);
            }

            document.getElementById('loading').classList.add('hidden');
            document.getElementById('invoice-list-section').classList.remove('hidden');
            document.getElementById('editing-section').classList.remove('hidden');
            refreshSummaryTemplateStatus();

        } catch (error) {
            console.error('Error loading conversion files:', error);
            document.getElementById('loading').classList.add('hidden');
            document.getElementById('upload-section').classList.remove('hidden');
            showError(`Failed to load files from conversion: ${error.message}. Please try uploading the CSV files manually.`);
        }
    }
})();

document.getElementById('upload-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const formData = new FormData();
    const fileInput = document.getElementById('csv_file');

    if (!fileInput.files || fileInput.files.length === 0) {
        showError('Please select at least one CSV file');
        return;
    }

    for (let i = 0; i < fileInput.files.length; i++) {
        formData.append('files', fileInput.files[i]);
    }

    document.getElementById('upload-section').classList.add('hidden');
    document.getElementById('loading').classList.remove('hidden');
    document.getElementById('error').classList.add('hidden');

    try {
        const response = await fetch('/api/upload-csv', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Processing failed');
        }

        const data = await response.json();
        batchSessionId = data.batch_session_id;
        allInvoices = data.invoices;
        currentInvoiceIndex = 0;

        populateInvoiceList(data.invoices);

        if (data.invoices.length > 0) {
            loadInvoice(data.invoices[0]);
        }

        document.getElementById('loading').classList.add('hidden');
        document.getElementById('invoice-list-section').classList.remove('hidden');
        document.getElementById('editing-section').classList.remove('hidden');
        refreshSummaryTemplateStatus();

    } catch (error) {
        document.getElementById('loading').classList.add('hidden');
        document.getElementById('upload-section').classList.remove('hidden');
        showError(error.message);
    }
});

async function refreshSummaryTemplateStatus() {
    if (!batchSessionId || !currentSessionId) return;
    try {
        const r = await fetch(`/api/summary-template-status/${batchSessionId}/${currentSessionId}`);
        if (!r.ok) return;
        const data = await r.json();
        const statusEl = document.getElementById('summary-template-status');
        const changeBtn = document.getElementById('summary-template-change-btn');
        if (data.has_template && data.has_mapping) {
            statusEl.textContent = 'Summary sheet set for this invoice. Filled sheet included when you download this invoice or the full ZIP.';
            statusEl.classList.remove('hidden');
            changeBtn.classList.remove('hidden');
        } else if (data.has_template) {
            statusEl.textContent = 'Template uploaded. Open "Change template / mapping" to set column mapping.';
            statusEl.classList.remove('hidden');
            changeBtn.classList.remove('hidden');
        } else {
            statusEl.classList.add('hidden');
            changeBtn.classList.add('hidden');
        }
    } catch (e) {
        console.error('Summary template status:', e);
    }
}

let summaryCalculatedFields = [];
async function openColumnMappingModal(columns, sourceHeaders, currentMapping, sourceFilename, summaryTemplateFilename) {
    summaryTemplateColumns = columns;
    if (!sourceHeaders || sourceHeaders.length === 0) {
        showError('No CSV headers available for the selected invoice. Make sure you have selected the invoice whose CSV you want to map from.');
        return;
    }
    if (summaryCalculatedFields.length === 0) {
        try {
            const r = await fetch('/api/summary-calculated-fields');
            if (r.ok) summaryCalculatedFields = (await r.json()).fields;
        } catch (e) {}
    }
    const ontoName = summaryTemplateFilename || 'Summary sheet';
    const fromName = sourceFilename || 'Source CSV';
    document.getElementById('column-mapping-label-onto').textContent = ontoName + ' (mapping onto)';
    document.getElementById('column-mapping-label-from').textContent = fromName + ' (mapping from)';
    document.getElementById('column-mapping-description').innerHTML =
        'For each column in <strong>' + ontoName + '</strong> (mapping onto), choose a column from <strong>' + fromName + '</strong> (source CSV) or a <strong>calculated field</strong> from the invoice/UI (e.g. Line Total, Wait \u00a3).';
    const listEl = document.getElementById('column-mapping-list');
    listEl.innerHTML = '';
    const emptyOpt = '<option value="">\u2014 Don\'t map \u2014</option>';
    const escapeAttr = (s) => String(s).replace(/"/g, '&quot;').replace(/</g, '&lt;');
    summaryTemplateColumns.forEach(col => {
        let selected = '';
        if (currentMapping && currentMapping[col] !== undefined && currentMapping[col] !== '') {
            selected = currentMapping[col];
        } else {
            if (sourceHeaders.indexOf(col) !== -1) selected = col;
        }
        const row = document.createElement('div');
        row.className = 'grid grid-cols-2 gap-3 items-center';
        const optsWithSelected = (sourceHeaders.map(h => `<option value="${escapeAttr(h)}" ${h === selected ? 'selected' : ''}>${escapeAttr(h)}</option>`).join('')) +
            (summaryCalculatedFields.length ? '<option disabled>\u2014\u2014 Calculated \u2014\u2014</option>' + summaryCalculatedFields.map(f => `<option value="${escapeAttr(f.id)}" ${f.id === selected ? 'selected' : ''}>${escapeAttr(f.label)}</option>`).join('') : '');
        row.innerHTML = `
            <span class="text-sm font-medium text-gray-700 min-w-0 truncate" title="${escapeAttr(col)}">${escapeAttr(col)}</span>
            <select class="column-mapping-select border border-gray-300 rounded px-3 py-2 text-sm" data-column="${escapeAttr(col)}">
                ${emptyOpt}
                ${optsWithSelected}
            </select>
        `;
        listEl.appendChild(row);
    });
    const sourceNameEl = document.getElementById('column-mapping-source-name');
    if (sourceFilename) {
        sourceNameEl.textContent = 'Source CSV (mapping from): ' + sourceFilename;
        sourceNameEl.classList.remove('hidden');
    } else {
        sourceNameEl.classList.add('hidden');
    }
    document.getElementById('column-mapping-modal').classList.remove('hidden');
}

document.getElementById('summary-template-upload-btn').addEventListener('click', () => {
    document.getElementById('summary-template-file').click();
});
document.getElementById('summary-template-change-btn').addEventListener('click', async () => {
    if (!batchSessionId || !currentSessionId || !allInvoices.length) return;
    const inv = allInvoices[currentInvoiceIndex];
    const sourceHeaders = inv && inv.source_headers;
    try {
        const statusRes = await fetch(`/api/summary-template-status/${batchSessionId}/${currentSessionId}`);
        if (!statusRes.ok) return;
        const status = await statusRes.json();
        if (!status.has_template || !status.columns || status.columns.length === 0) {
            document.getElementById('summary-template-file').click();
            return;
        }
        await openColumnMappingModal(status.columns, sourceHeaders, status.mapping || {}, inv.filename, status.template_filename);
    } catch (e) {
        showError(e.message);
    }
});

document.getElementById('summary-template-file').addEventListener('change', async (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file || !batchSessionId || !currentSessionId) return;
    const inv = allInvoices[currentInvoiceIndex];
    const sourceHeaders = inv && inv.source_headers;
    const formData = new FormData();
    formData.append('batch_session_id', batchSessionId);
    formData.append('invoice_session_id', currentSessionId);
    formData.append('file', file);
    try {
        const res = await fetch('/api/upload-summary-template', { method: 'POST', body: formData });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Upload failed');
        }
        const data = await res.json();
        await openColumnMappingModal(data.columns, sourceHeaders, {}, inv ? inv.filename : null, data.template_filename);
    } catch (err) {
        showError(err.message);
    }
    e.target.value = '';
});

document.getElementById('column-mapping-save-btn').addEventListener('click', async () => {
    const mapping = {};
    document.querySelectorAll('.column-mapping-select').forEach(sel => {
        const col = sel.getAttribute('data-column');
        const val = sel.value;
        if (val) mapping[col] = val;
    });
    const formData = new FormData();
    formData.append('batch_session_id', batchSessionId);
    formData.append('invoice_session_id', currentSessionId);
    formData.append('mapping', JSON.stringify(mapping));
    try {
        const res = await fetch('/api/set-summary-mapping', { method: 'POST', body: formData });
        if (!res.ok) throw new Error('Failed to save mapping');
        document.getElementById('column-mapping-modal').classList.add('hidden');
        refreshSummaryTemplateStatus();
    } catch (err) {
        showError(err.message);
    }
});

document.getElementById('column-mapping-cancel-btn').addEventListener('click', () => {
    document.getElementById('column-mapping-modal').classList.add('hidden');
});
document.getElementById('column-mapping-modal-backdrop').addEventListener('click', () => {
    document.getElementById('column-mapping-modal').classList.add('hidden');
});

function populateInvoiceList(invoices) {
    const invoiceList = document.getElementById('invoice-list');
    invoiceList.innerHTML = '';

    invoices.forEach((invoice, index) => {
        const invoiceItem = document.createElement('div');
        invoiceItem.className = `flex justify-between items-center p-4 border border-gray-300 rounded-lg cursor-pointer transition duration-200 ${index === currentInvoiceIndex ? 'bg-blue-50 border-accent' : 'hover:bg-gray-50'}`;
        invoiceItem.onclick = () => {
            currentInvoiceIndex = index;
            loadInvoice(invoice);
            highlightCurrentInvoice();
        };

        invoiceItem.innerHTML = `
            <div class="flex-1">
                <p class="font-semibold text-gray-800">${invoice.filename}</p>
                <p class="text-sm text-gray-500">Invoice ${index + 1} of ${invoices.length}</p>
            </div>
            <button
                onclick="event.stopPropagation(); downloadSingleInvoice('${invoice.session_id}', '${invoice.filename}')"
                class="ml-4 bg-accent hover:bg-accent-dark text-white font-bold py-2 px-4 rounded-lg transition duration-200 text-sm"
            >
                Download
            </button>
        `;

        invoiceList.appendChild(invoiceItem);
    });

    const navButtons = document.getElementById('invoice-navigation');
    if (invoices.length > 1) {
        navButtons.style.display = 'flex';
    } else {
        navButtons.style.display = 'none';
    }
}

function loadInvoice(invoice) {
    if (currentSessionId && currentInvoiceData) {
        const currentInvoice = allInvoices.find(inv => inv.session_id === currentSessionId);
        if (currentInvoice) {
            const formData = collectFormData();
            currentInvoice.invoice_data = formData;
        }
    }

    currentSessionId = invoice.session_id;
    currentInvoiceData = invoice.invoice_data;
    populateForm(invoice.invoice_data);
    document.getElementById('current-invoice-name').textContent = invoice.filename;

    document.getElementById('prev-invoice-btn').disabled = currentInvoiceIndex === 0;
    document.getElementById('next-invoice-btn').disabled = currentInvoiceIndex === allInvoices.length - 1;

    refreshSummaryTemplateStatus();
}

function highlightCurrentInvoice() {
    document.querySelectorAll('#invoice-list > div').forEach((item, idx) => {
        if (idx === currentInvoiceIndex) {
            item.className = 'flex justify-between items-center p-4 border border-accent rounded-lg cursor-pointer transition duration-200 bg-blue-50';
        } else {
            item.className = 'flex justify-between items-center p-4 border border-gray-300 rounded-lg cursor-pointer transition duration-200 hover:bg-gray-50';
        }
    });
}

document.getElementById('prev-invoice-btn').addEventListener('click', () => {
    if (currentInvoiceIndex > 0) {
        currentInvoiceIndex--;
        loadInvoice(allInvoices[currentInvoiceIndex]);
        highlightCurrentInvoice();
    }
});

document.getElementById('next-invoice-btn').addEventListener('click', () => {
    if (currentInvoiceIndex < allInvoices.length - 1) {
        currentInvoiceIndex++;
        loadInvoice(allInvoices[currentInvoiceIndex]);
        highlightCurrentInvoice();
    }
});

async function downloadSingleInvoice(sessionId, filename) {
    try {
        const response = await fetch(`/api/download-invoice/${sessionId}`, {
            method: 'POST'
        });

        if (!response.ok) throw new Error('Download failed');

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename.replace('.csv', '.html');
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    } catch (error) {
        showError('Failed to download invoice');
    }
}

window.downloadSingleInvoice = downloadSingleInvoice;

document.getElementById('download-all-btn').addEventListener('click', async () => {
    if (!batchSessionId) {
        showError('No batch session found');
        return;
    }

    try {
        const formData = new FormData();
        formData.append('batch_session_id', batchSessionId);

        const response = await fetch('/api/download-all-invoices', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) throw new Error('Download failed');

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `invoices_${batchSessionId}.zip`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    } catch (error) {
        showError('Failed to download all invoices');
    }
});

document.getElementById('edit-summary-btn').addEventListener('click', async () => {
    if (!currentSessionId) {
        showError('Please upload a CSV file first');
        return;
    }

    const selectedCheckboxes = document.querySelectorAll('.item-checkbox:checked');
    if (selectedCheckboxes.length === 0) {
        showError('Please select at least one line item');
        return;
    }

    const formData = collectFormData();
    const formDataToSend = new FormData();
    formDataToSend.append('invoice_data_json', JSON.stringify(formData));

    try {
        const response = await fetch(`/api/generate-summary-data/${currentSessionId}`, {
            method: 'POST',
            body: formDataToSend
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to generate summary data');
        }

        const summaryData = await response.json();
        sessionStorage.setItem('summaryEditorData', JSON.stringify(summaryData));
        window.open(`/summary-editor?session_id=${currentSessionId}`, '_blank');
    } catch (error) {
        showError(error.message || 'Failed to open summary editor');
    }
});

document.getElementById('invoice-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    if (!currentSessionId) {
        showError('Please upload a CSV file first');
        return;
    }

    const selectedCheckboxes = document.querySelectorAll('.item-checkbox:checked');
    if (selectedCheckboxes.length === 0) {
        showError('Please select at least one line item to include in the invoice');
        return;
    }

    const formData = collectFormData();

    if (allInvoices[currentInvoiceIndex]) {
        allInvoices[currentInvoiceIndex].invoice_data = formData;
    }

    const formDataToSend = new FormData();
    formDataToSend.append('session_id', currentSessionId);
    formDataToSend.append('invoice_data_json', JSON.stringify(formData));

    try {
        const response = await fetch('/api/update-invoice', {
            method: 'POST',
            body: formDataToSend
        });

        if (!response.ok) throw new Error('Generation failed');

        const blob = await response.blob();
        const contentType = response.headers.get('content-type') || '';
        const contentDisp = response.headers.get('content-disposition') || '';
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const currentFilename = allInvoices[currentInvoiceIndex]?.filename || 'invoice';
        const baseName = currentFilename.replace(/\.csv$/i, '');
        if (contentType.indexOf('application/zip') !== -1 || blob.type === 'application/zip') {
            a.download = baseName + '_invoice_and_summary.zip';
        } else {
            const match = contentDisp.match(/filename="?([^";\n]+)"?/);
            a.download = match ? match[1].trim() : (baseName + '.html');
        }
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        document.getElementById('success').classList.remove('hidden');
    } catch (error) {
        showError('Failed to generate invoice');
    }
});
