/* Stage 3 (Invoice Editing) — HTML upload and single-invoice download. */

document.getElementById('upload-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const formData = new FormData();
    const fileInput = document.getElementById('html_file');

    if (!fileInput.files || fileInput.files.length === 0) {
        showError('Please select an HTML file');
        return;
    }

    formData.append('file', fileInput.files[0]);

    document.getElementById('upload-section').classList.add('hidden');
    document.getElementById('loading').classList.remove('hidden');
    document.getElementById('error').classList.add('hidden');

    try {
        const response = await fetch('/api/upload-html', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Processing failed');
        }

        const data = await response.json();
        currentSessionId = data.session_id;
        currentInvoiceData = data.invoice_data;

        populateForm(data.invoice_data);
        document.getElementById('current-invoice-name').textContent = data.filename;

        document.getElementById('loading').classList.add('hidden');
        document.getElementById('editing-section').classList.remove('hidden');

    } catch (error) {
        document.getElementById('loading').classList.add('hidden');
        document.getElementById('upload-section').classList.remove('hidden');
        showError(error.message);
    }
});

document.getElementById('invoice-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    if (!currentSessionId) {
        showError('Please upload an HTML invoice file first');
        return;
    }

    const selectedCheckboxes = document.querySelectorAll('.item-checkbox:checked');
    if (selectedCheckboxes.length === 0) {
        showError('Please select at least one line item to include in the invoice');
        return;
    }

    const formData = collectFormData();

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
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const currentFilename = document.getElementById('current-invoice-name').textContent || 'invoice';
        a.download = currentFilename.endsWith('.html') ? currentFilename : currentFilename + '.html';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        document.getElementById('success').classList.remove('hidden');
    } catch (error) {
        showError('Failed to generate invoice');
    }
});
