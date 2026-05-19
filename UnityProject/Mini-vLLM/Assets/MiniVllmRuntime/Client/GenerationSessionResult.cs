using MiniVllm.Runtime.V1;

namespace MiniVllm.Runtime.Client
{
    public sealed class GenerationSession
    {
        public GenerationSession(string requestId, System.Threading.Tasks.Task<GenerationSessionResult> completion)
        {
            RequestId = requestId;
            Completion = completion;
        }

        public string RequestId { get; }
        public System.Threading.Tasks.Task<GenerationSessionResult> Completion { get; }
    }

    public sealed class GenerationSessionResult
    {
        public GenerationSessionResult(
            string requestId,
            string streamedText,
            DoneReply done)
        {
            RequestId = requestId;
            StreamedText = streamedText;
            Done = done;
        }

        public string RequestId { get; }
        public string StreamedText { get; }
        public DoneReply Done { get; }
    }
}
