using System;
using UnityEngine;

namespace MiniVllm.Runtime.Client
{
    public sealed class MiniVllmPhase2Probe : MonoBehaviour
    {
        [SerializeField]
        private string prompt = "Hello";

        [SerializeField]
        private int maxNewTokens = 8;

        [ContextMenu("Run Phase 2 Generate Probe")]
        public async void RunPhase2GenerateProbe()
        {
            try
            {
                using var client = new MiniVllmClient();
                await client.ConnectAsync();

                var result = await client.GenerateAsync(
                    prompt,
                    token => Debug.Log($"TOKEN[{token.Index}] '{token.Text}'"),
                    maxNewTokens);

                Debug.Log(
                    $"DONE: finishReason={result.Done.FinishReason}, " +
                    $"streamed='{result.StreamedText}', final='{result.Done.Text}'");
            }
            catch (Exception ex)
            {
                Debug.LogError($"MiniVLLM Phase 2 probe failed: {ex}");
            }
        }
    }
}
