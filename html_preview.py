import pickle
import sys
import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


def render_invoice_html(invoice_data_pkl_path, template_name='Invoice 2.html', output_file=None):
    """
    Load invoice data and render it into an HTML file.
    
    Args:
        invoice_data_pkl_path (str): Path to the invoice data pickle file
        template_name (str): Name of the template file in the templates directory
        output_file (str, optional): Output HTML file path. If None, auto-generates from input.
    
    Returns:
        str: Path to the generated HTML file
    """
    # Load invoice data from pickle file
    if not os.path.exists(invoice_data_pkl_path):
        raise FileNotFoundError(f"Invoice data file not found: {invoice_data_pkl_path}")
    
    with open(invoice_data_pkl_path, 'rb') as f:
        invoice_data = pickle.load(f)
    
    print(f"Loaded invoice data from: {invoice_data_pkl_path}")
    print(f"Patient: {invoice_data['patient']['name']}")
    print(f"Number of items: {len(invoice_data['invoice']['items'])}")
    
    # Set up Jinja2 environment
    templates_dir = Path(__file__).parent / 'templates'
    if not templates_dir.exists():
        raise FileNotFoundError(f"Templates directory not found: {templates_dir}")
    
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    template = env.get_template(template_name)
    
    # Render the template with the invoice data
    rendered_html = template.render(data=invoice_data)
    
    # Fix image path for standalone HTML (change /static/ to relative path)
    # Check if image exists in templates directory, otherwise use static
    templates_img = Path(__file__).parent / 'templates' / 'Picture1.jpg'
    static_img = Path(__file__).parent / 'static' / 'Picture1.jpg'
    
    if templates_img.exists():
        # Use relative path to templates directory
        rendered_html = rendered_html.replace('/static/Picture1.jpg', 'templates/Picture1.jpg')
    elif static_img.exists():
        # Use relative path to static directory
        rendered_html = rendered_html.replace('/static/Picture1.jpg', 'static/Picture1.jpg')
    
    # Create "invoice html" folder if it doesn't exist
    invoice_html_dir = Path(__file__).parent / 'invoice html'
    invoice_html_dir.mkdir(exist_ok=True)
    
    # Determine output file path
    if output_file is None:
        output_filename = Path(invoice_data_pkl_path).stem.replace('_invoice_data', '') + '_preview.html'
        output_file = invoice_html_dir / output_filename
    else:
        # If custom path provided, ensure it's in the invoice html folder
        output_file = Path(output_file)
        if not output_file.is_absolute():
            output_file = invoice_html_dir / output_file
    
    # Save the rendered HTML
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(rendered_html)
    
    print(f"\nHTML invoice generated successfully!")
    print(f"Output file: {os.path.abspath(output_file)}")
    print(f"\nYou can open this file in your browser to preview the invoice.")
    
    return str(output_file)


if __name__ == "__main__":
    # Get invoice data pickle file path from command line argument
    if len(sys.argv) > 1:
        pkl_path = sys.argv[1]
    else:
        # Prompt user for file path if not provided
        pkl_path = input("Enter the path to the invoice data pickle file: ").strip().strip('"')
    
    # Optional: Get output file path
    output_path = None
    if len(sys.argv) > 2:
        output_path = sys.argv[2]
    
    # Optional: Get template name
    template_name = 'Invoice 2.html'
    if len(sys.argv) > 3:
        template_name = sys.argv[3]
    
    try:
        html_file = render_invoice_html(pkl_path, template_name, output_path)
        print(f"\nTo open in browser, run:")
        print(f'start {html_file}')
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

