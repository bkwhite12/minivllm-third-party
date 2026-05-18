using System;
using System.Threading.Tasks;
using UnityEngine;

namespace MiniVllm.Runtime.Client
{
    public sealed class MiniVllmPhase1Probe : MonoBehaviour
    {
        [ContextMenu("Run Phase 1 Probe")]
        public async void RunPhase1Probe()
        {
            try
            {
                using var client = new MiniVllmClient();
                await client.ConnectAsync();
                var hello = await client.HelloAsync("unity-phase1-probe", "0.1.0-dev");
                var health = await client.HealthAsync();

                Debug.Log(
                    $"MiniVLLM connected: worker={hello.WorkerName} {hello.WorkerVersion}, " +
                    $"model={health.ActiveModel}, backend={health.Backend}, kernelPack={health.KernelPackId}");
            }
            catch (Exception ex)
            {
                Debug.LogError($"MiniVLLM Phase 1 probe failed: {ex}");
            }
        }
    }
}
