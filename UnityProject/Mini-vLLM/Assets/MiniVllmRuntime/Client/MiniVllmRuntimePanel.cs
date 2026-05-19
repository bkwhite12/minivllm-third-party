using System;
using System.Threading.Tasks;
using MiniVllm.Runtime.V1;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace MiniVllm.Runtime.Client
{
    public sealed class MiniVllmRuntimePanel : MonoBehaviour
    {
        [Header("Inputs")]
        [SerializeField] private TMP_InputField promptInput;
        [SerializeField] private int maxNewTokens = 32;

        [Header("Buttons")]
        [SerializeField] private Button connectButton;
        [SerializeField] private Button generateButton;
        [SerializeField] private Button cancelButton;
        [SerializeField] private Button metricsButton;

        [Header("Outputs")]
        [SerializeField] private TMP_Text statusText;
        [SerializeField] private TMP_Text outputText;
        [SerializeField] private TMP_Text metricsText;

        private MiniVllmClient _client;
        private string _activeRequestId;
        private bool _isGenerating;

        private void Awake()
        {
            connectButton?.onClick.AddListener(() => _ = ConnectAsync());
            generateButton?.onClick.AddListener(() => _ = GenerateAsync());
            cancelButton?.onClick.AddListener(() => _ = CancelAsync());
            metricsButton?.onClick.AddListener(() => _ = RefreshMetricsAsync());
            SetGenerating(false);
        }

        private void OnDestroy()
        {
            _client?.Dispose();
        }

        public async Task ConnectAsync()
        {
            try
            {
                _client?.Dispose();
                _client = new MiniVllmClient();
                await _client.ConnectAsync();
                var hello = await _client.HelloAsync("unity-runtime-panel", "0.1.0-dev");
                var health = await _client.HealthAsync();
                SetStatus(
                    $"Connected: {hello.WorkerName} {hello.WorkerVersion}\n" +
                    $"Model: {health.ActiveModel}\n" +
                    $"Backend: {health.Backend}\n" +
                    $"Kernel: {health.KernelPackId}");
            }
            catch (Exception ex)
            {
                SetStatus($"Connect failed:\n{ex.Message}");
            }
        }

        public async Task GenerateAsync()
        {
            if (_client == null || !_client.IsConnected)
            {
                SetStatus("Not connected.");
                return;
            }

            if (_isGenerating)
            {
                return;
            }

            try
            {
                SetGenerating(true);
                outputText.text = string.Empty;
                var session = _client.StartGeneration(
                    promptInput != null ? promptInput.text : string.Empty,
                    token =>
                    {
                        outputText.text += token.Text;
                    },
                    maxNewTokens);
                _activeRequestId = session.RequestId;
                var result = await session.Completion;
                SetStatus($"Done: {result.Done.FinishReason}");
            }
            catch (Exception ex)
            {
                SetStatus($"Generate failed:\n{ex.Message}");
            }
            finally
            {
                _activeRequestId = null;
                SetGenerating(false);
            }
        }

        public async Task CancelAsync()
        {
            if (_client == null || !_client.IsConnected || string.IsNullOrEmpty(_activeRequestId))
            {
                SetStatus("No active request to cancel.");
                return;
            }

            try
            {
                var reply = await _client.CancelAsync(_activeRequestId);
                SetStatus(reply.Accepted ? "Cancel accepted." : "Cancel rejected.");
            }
            catch (Exception ex)
            {
                SetStatus($"Cancel failed:\n{ex.Message}");
            }
        }

        public async Task RefreshMetricsAsync()
        {
            if (_client == null || !_client.IsConnected)
            {
                SetStatus("Not connected.");
                return;
            }

            try
            {
                var metrics = await _client.MetricsAsync();
                var runtime = metrics.Runtime;
                metricsText.text =
                    $"uptime: {runtime.ProcessUptimeMs} ms\n" +
                    $"total: {runtime.TotalRequests}\n" +
                    $"completed: {runtime.CompletedRequests}\n" +
                    $"cancelled: {runtime.CancelledRequests}\n" +
                    $"eos: {runtime.EosCompletions}\n" +
                    $"max-token: {runtime.MaxTokenCompletions}\n" +
                    $"failed: {runtime.FailedRequests}\n" +
                    $"active: {runtime.ActiveRequests}\n" +
                    $"allocated VRAM: {runtime.AllocatedVramBytes}\n" +
                    $"reserved VRAM: {runtime.ReservedVramBytes}";
            }
            catch (Exception ex)
            {
                SetStatus($"Metrics failed:\n{ex.Message}");
            }
        }

        private void SetGenerating(bool value)
        {
            _isGenerating = value;
            if (generateButton != null) generateButton.interactable = !value;
            if (cancelButton != null) cancelButton.interactable = value;
        }

        private void SetStatus(string value)
        {
            if (statusText != null)
            {
                statusText.text = value;
            }
        }
    }
}
