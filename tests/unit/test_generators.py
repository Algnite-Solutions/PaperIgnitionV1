"""Unit tests for core.generators prompt formatting."""
from core.generators import _format_figure_info, format_blog_prompt
from core.models import FigureChunk


def test_format_figure_info_no_figures():
    result = _format_figure_info([], "./imgs/")
    assert "No figures available" in result
    assert "Do not cite any figures" in result


def test_format_figure_info_none():
    result = _format_figure_info(None, "./imgs/")
    assert "No figures available" in result


def test_format_figure_info_single_figure():
    figs = [
        FigureChunk(
            title="2501.01234_Figure1",
            caption="Architecture overview",
            image_path="imgs/2501.01234_Figure1.png",
        )
    ]
    result = _format_figure_info(figs, "./imgs")
    assert "ONLY use figures from this list" in result
    assert "Figure 1" in result
    assert "Architecture overview" in result
    assert "![Figure 1:" in result
    assert "./imgs/2501.01234_Figure1.png" in result


def test_format_figure_info_multiple_figures():
    figs = [
        FigureChunk(title="2501.01234_Figure1", caption="Pipeline"),
        FigureChunk(title="2501.01234_Figure3", caption="Results"),
    ]
    result = _format_figure_info(figs, "./imgs")
    assert "Figure 1" in result
    assert "Figure 3" in result
    assert result.count("- Figure") == 2


def test_format_blog_prompt_chinese_default():
    prompt = format_blog_prompt(
        data_path="./imgs",
        arxiv_id="2501.01234",
        text_chunks="",
        table_chunks="",
        figure_chunks="No figures available.",
        title="Test Paper",
        input_format="pdf",
    )
    # Default is Chinese
    assert "你是一个专业的科技博客作者" in prompt
    assert "Test Paper" in prompt


def test_format_blog_prompt_chinese_explicit():
    prompt = format_blog_prompt(
        data_path="./imgs",
        arxiv_id="2501.01234",
        text_chunks="",
        table_chunks="",
        figure_chunks="No figures available.",
        title="Test Paper",
        input_format="pdf",
        language="zh",
    )
    assert "你是一个专业的科技博客作者" in prompt


def test_format_blog_prompt_english():
    prompt = format_blog_prompt(
        data_path="./imgs",
        arxiv_id="2501.01234",
        text_chunks="",
        table_chunks="",
        figure_chunks="No figures available.",
        title="Test Paper",
        input_format="pdf",
        language="en",
    )
    assert "professional tech blogger" in prompt
    assert "Test Paper" in prompt
    # Should NOT contain Chinese prompt
    assert "你是一个专业的科技博客作者" not in prompt


def test_format_blog_prompt_figure_instruction_zh():
    """Chinese prompt should contain the updated figure-only-from-list instruction."""
    prompt = format_blog_prompt(
        data_path="./imgs",
        arxiv_id="2501.01234",
        text_chunks="",
        table_chunks="",
        figure_chunks="Available Figures (ONLY use figures from this list)",
        title="Test",
        input_format="pdf",
        language="zh",
    )
    assert "Available Figures" in prompt


def test_format_blog_prompt_figure_instruction_en():
    """English prompt should contain the updated figure-only-from-list instruction."""
    prompt = format_blog_prompt(
        data_path="./imgs",
        arxiv_id="2501.01234",
        text_chunks="",
        table_chunks="",
        figure_chunks="Available Figures (ONLY use figures from this list)",
        title="Test",
        input_format="pdf",
        language="en",
    )
    assert "ONLY cite figures from" in prompt
