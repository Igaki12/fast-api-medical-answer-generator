import { useEffect, useMemo, useRef, useState } from "react";
import {
  Badge,
  Box,
  Button,
  Container,
  Divider,
  FormControl,
  FormLabel,
  Grid,
  GridItem,
  Heading,
  HStack,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  SimpleGrid,
  SlideFade,
  Stack,
  Text,
  VStack
} from "@chakra-ui/react";
import { ApiError, downloadResult, getJobStatus, startLegacyPipeline } from "./lib/api";
import { keyframes } from "@emotion/react";

const STORAGE_KEY = "pipeline_jobs";
const FORM_STORAGE_KEY = "pipeline_form_defaults";

type JobRecord = {
  jobId: string;
  status: string;
  explanationName: string;
  year?: string;
  subject?: string;
  university?: string;
  author?: string;
  createdAt: string;
  updatedAt: string;
  message?: string;
  error?: string;
};

const tips = [
  "最大15分程度待つ可能性があります。",
  "大きいファイルや多数の画像で失敗する可能性があります。",
  "失敗時は分割して再実行すると成功する場合があります。"
];

const statusLabels: Record<string, string> = {
  accepted: "受付済み",
  queued: "受付済み",
  generating_md: "Markdown 生成中",
  generating_pdf: "PDF 生成中",
  done: "完了",
  failed: "失敗",
  failed_to_convert: "PDF変換失敗（Markdownのみ）",
  expired: "期限切れ"
};

const statusBadgeStyles: Record<string, { bg: string; color: string }> = {
  accepted: { bg: "#F8E9C6", color: "#6D5F4B" },
  queued: { bg: "#F8E9C6", color: "#6D5F4B" },
  generating_md: { bg: "#FBE7B3", color: "#6D5F4B" },
  generating_pdf: { bg: "#FBE1A1", color: "#6D5F4B" },
  done: { bg: "#E6F4DD", color: "#2B593F" },
  failed: { bg: "#F7D6D2", color: "#7C2E2E" },
  failed_to_convert: { bg: "#F2E0C8", color: "#6D5F4B" },
  expired: { bg: "#EFE7DA", color: "#6D5F4B" }
};

const pendingStatuses = [
  "accepted",
  "queued",
  "generating_md",
  "generating_pdf",
  "processing",
  "running",
  "converting"
];

function loadJobs(): JobRecord[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed as JobRecord[];
  } catch {
    return [];
  }
}

function saveJobs(jobs: JobRecord[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs));
}

type FormDefaults = {
  year: string;
  subject: string;
  university: string;
  author: string;
  explanationName: string;
};

function loadFormDefaults(): Partial<FormDefaults> {
  try {
    const raw = localStorage.getItem(FORM_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    return parsed as Partial<FormDefaults>;
  } catch {
    return {};
  }
}

function saveFormDefaults(values: FormDefaults) {
  localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(values));
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("ja-JP");
}

type StatusResult = {
  jobId: string;
  data?: { status?: string; message?: string; error?: string };
  error?: unknown;
};

function mergeStatusResults(prev: JobRecord[], results: StatusResult[]) {
  const now = new Date().toISOString();
  return prev.map((job) => {
    const match = results.find((item) => item.jobId === job.jobId);
    if (!match) return job;
    if (match.error) {
      if (match.error instanceof ApiError && [404, 410].includes(match.error.status)) {
        return {
          ...job,
          status: "expired",
          updatedAt: now,
          error: match.error.message
        };
      }
      return {
        ...job,
        updatedAt: now,
        error: match.error instanceof Error ? match.error.message : "Unknown error"
      };
    }
    if (!match.data) {
      return job;
    }
    return {
      ...job,
      status: match.data.status ?? job.status,
      message: match.data.message,
      error: match.data.error,
      updatedAt: now
    };
  });
}

export default function App() {
  const defaults = loadFormDefaults();
  const [apiKey, setApiKey] = useState("");
  const [year, setYear] = useState(defaults.year ?? "");
  const [subject, setSubject] = useState(defaults.subject ?? "");
  const [university, setUniversity] = useState(defaults.university ?? "");
  const [author, setAuthor] = useState(defaults.author ?? "");
  const [explanationName, setExplanationName] = useState(defaults.explanationName ?? "");
  const [userEditedName, setUserEditedName] = useState(false);
  const [inputFile, setInputFile] = useState<File | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobRecord[]>(() => loadJobs());
  const [tipIndex, setTipIndex] = useState(0);
  const [downloadingJobId, setDownloadingJobId] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [retryJob, setRetryJob] = useState<JobRecord | null>(null);
  const [retryApiKey, setRetryApiKey] = useState("");
  const [retryYear, setRetryYear] = useState("");
  const [retrySubject, setRetrySubject] = useState("");
  const [retryUniversity, setRetryUniversity] = useState("");
  const [retryAuthor, setRetryAuthor] = useState("");
  const [retryExplanationName, setRetryExplanationName] = useState("");
  const [retryUserEditedName, setRetryUserEditedName] = useState(false);
  const [retryFile, setRetryFile] = useState<File | null>(null);
  const [isRetryOpen, setIsRetryOpen] = useState(false);
  const pollingRef = useRef<number | null>(null);

  useEffect(() => {
    saveJobs(jobs);
  }, [jobs]);

  useEffect(() => {
    if (userEditedName) return;
    if (!year && !subject) {
      setExplanationName("");
      return;
    }
    const base = [year, subject].filter(Boolean).join("_");
    setExplanationName(`${base}_解答解説`);
  }, [year, subject, userEditedName]);

  useEffect(() => {
    saveFormDefaults({
      year: year.trim(),
      subject: subject.trim(),
      university: university.trim(),
      author: author.trim(),
      explanationName: explanationName.trim()
    });
  }, [year, subject, university, author, explanationName]);

  useEffect(() => {
    if (!isRetryOpen) return;
    if (retryUserEditedName) return;
    if (!retryYear && !retrySubject) {
      setRetryExplanationName("");
      return;
    }
    const base = [retryYear, retrySubject].filter(Boolean).join("_");
    setRetryExplanationName(`${base}_解答解説`);
  }, [retryYear, retrySubject, retryUserEditedName, isRetryOpen]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setTipIndex((prev) => (prev + 1) % tips.length);
    }, 4200);
    return () => window.clearTimeout(timer);
  }, [tipIndex]);

  const pendingJobs = useMemo(
    () =>
      jobs.filter((job) => pendingStatuses.includes(job.status)),
    [jobs]
  );

  const refreshPendingJobs = async () => {
    setErrorMessage(null);
    const targets = jobs.filter((job) => pendingStatuses.includes(job.status));
    if (targets.length === 0) {
      setStatusMessage("更新する待機中ジョブがありません。");
      return;
    }
    setIsRefreshing(true);
    setStatusMessage("ステータスを更新中...");
    const results = await Promise.all(
      targets.map(async (job) => {
        try {
          const data = await getJobStatus(job.jobId);
          return { jobId: job.jobId, data };
        } catch (error) {
          return { jobId: job.jobId, error };
        }
      })
    );
    setJobs((prev) => mergeStatusResults(prev, results));
    setIsRefreshing(false);
    setStatusMessage("ステータスを更新しました。");
  };

  useEffect(() => {
    if (pendingJobs.length === 0) return;
    if (pollingRef.current) {
      window.clearTimeout(pollingRef.current);
    }
    const controller = new AbortController();

    pollingRef.current = window.setTimeout(async () => {
      const results = await Promise.all(
        pendingJobs.map(async (job) => {
          try {
            const data = await getJobStatus(job.jobId, controller.signal);
            return { jobId: job.jobId, data };
          } catch (error) {
            return { jobId: job.jobId, error };
          }
        })
      );

      setJobs((prev) => mergeStatusResults(prev, results));
    }, 10000);

    return () => {
      controller.abort();
      if (pollingRef.current) {
        window.clearTimeout(pollingRef.current);
      }
    };
  }, [pendingJobs]);

  const canSubmit =
    explanationName.trim() &&
    year.trim() &&
    subject.trim() &&
    university.trim() &&
    author.trim() &&
    inputFile;

  const retryCanSubmit =
    retryExplanationName.trim() &&
    retryYear.trim() &&
    retrySubject.trim() &&
    retryUniversity.trim() &&
    retryAuthor.trim() &&
    retryFile;

  const onSubmit = async () => {
    if (!inputFile || !canSubmit) {
      setErrorMessage("必須項目を入力し、ファイルを選択してください。");
      return;
    }
    setErrorMessage(null);
    setStatusMessage("ジョブを開始しています...");

    try {
      const res = await startLegacyPipeline({
        apiKey: apiKey.trim() || undefined,
        file: inputFile,
        explanationName: explanationName.trim(),
        university: university.trim(),
        year: year.trim(),
        subject: subject.trim(),
        author: author.trim()
      });

      const now = new Date().toISOString();
      const job: JobRecord = {
        jobId: res.job_id,
        status: res.status ?? "queued",
        explanationName: explanationName.trim(),
        year: year.trim(),
        subject: subject.trim(),
        university: university.trim(),
        author: author.trim(),
        createdAt: now,
        updatedAt: now,
        message: res.message
      };

      saveFormDefaults({
        year: year.trim(),
        subject: subject.trim(),
        university: university.trim(),
        author: author.trim(),
        explanationName: explanationName.trim()
      });
      setJobs((prev) => [job, ...prev]);
      setStatusMessage("ジョブを受付しました。完了までお待ちください。");
    } catch (error) {
      setStatusMessage(null);
      setErrorMessage(error instanceof Error ? error.message : "送信に失敗しました。");
    }
  };

  const handleDownload = async (jobId: string) => {
    setErrorMessage(null);
    setDownloadingJobId(jobId);
    try {
      await downloadResult(jobId);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setJobs((prev) =>
          prev.map((job) =>
            job.jobId === jobId
              ? {
                  ...job,
                  status: "failed_to_convert",
                  updatedAt: new Date().toISOString(),
                  error: "PDF変換に失敗しました。再試行してください。"
                }
              : job
          )
        );
        setErrorMessage("PDF変換に失敗しました。再試行してください。");
      } else {
        setErrorMessage(error instanceof Error ? error.message : "ダウンロードに失敗しました。");
      }
    } finally {
      setDownloadingJobId(null);
    }
  };

  const openRetryModal = (job: JobRecord) => {
    const stored = loadFormDefaults();
    setRetryJob(job);
    setRetryApiKey("");
    setRetryYear(job.year ?? stored.year ?? "");
    setRetrySubject(job.subject ?? stored.subject ?? "");
    setRetryUniversity(job.university ?? stored.university ?? "");
    setRetryAuthor(job.author ?? stored.author ?? "");
    setRetryExplanationName(job.explanationName || stored.explanationName || "");
    setRetryUserEditedName(Boolean(job.explanationName || stored.explanationName));
    setRetryFile(null);
    setIsRetryOpen(true);
  };

  const closeRetryModal = () => {
    setIsRetryOpen(false);
    setRetryJob(null);
    setRetryFile(null);
  };

  const onRetrySubmit = async () => {
    if (!retryFile || !retryCanSubmit) {
      setErrorMessage("必須項目を入力し、ファイルを選択してください。");
      return;
    }
    setErrorMessage(null);
    setStatusMessage("ジョブを開始しています...");

    try {
      const res = await startLegacyPipeline({
        apiKey: retryApiKey.trim() || undefined,
        file: retryFile,
        explanationName: retryExplanationName.trim(),
        university: retryUniversity.trim(),
        year: retryYear.trim(),
        subject: retrySubject.trim(),
        author: retryAuthor.trim()
      });

      const now = new Date().toISOString();
      const job: JobRecord = {
        jobId: res.job_id,
        status: res.status ?? "queued",
        explanationName: retryExplanationName.trim(),
        year: retryYear.trim(),
        subject: retrySubject.trim(),
        university: retryUniversity.trim(),
        author: retryAuthor.trim(),
        createdAt: now,
        updatedAt: now,
        message: res.message
      };

      saveFormDefaults({
        year: retryYear.trim(),
        subject: retrySubject.trim(),
        university: retryUniversity.trim(),
        author: retryAuthor.trim(),
        explanationName: retryExplanationName.trim()
      });

      setJobs((prev) => [job, ...prev]);
      setStatusMessage("ジョブを受付しました。完了までお待ちください。");
      closeRetryModal();
    } catch (error) {
      setStatusMessage(null);
      setErrorMessage(error instanceof Error ? error.message : "送信に失敗しました。");
    }
  };

  const loadingBar = keyframes`
    0% { transform: scaleX(0); }
    100% { transform: scaleX(1); }
  `;

  const shapeShift = keyframes`
    0% { border-radius: 50%; transform: scale(1); }
    33% { border-radius: 10%; transform: scale(1.1) rotate(20deg); }
    66% { border-radius: 0%; transform: scale(0.9) rotate(-10deg); }
    100% { border-radius: 50%; transform: scale(1); }
  `;

  return (
    <Box minH="100vh" pb={{ base: 10, md: 16 }} position="relative" overflow="hidden">
      <Box
        position="absolute"
        top="-120px"
        right="-120px"
        w="320px"
        h="320px"
        bg="brand.gold"
        opacity={0.12}
        filter="blur(12px)"
        borderRadius="50%"
      />
      <Box
        position="absolute"
        bottom="-160px"
        left="-120px"
        w="360px"
        h="360px"
        bg="brand.goldDeep"
        opacity={0.08}
        filter="blur(18px)"
        borderRadius="45%"
      />

      <Container maxW="6xl" pt={{ base: 10, md: 14 }}>
        <VStack spacing={{ base: 8, md: 12 }} align="stretch">
          <Stack spacing={2} textAlign={{ base: "left", md: "center" }}>
            <Heading fontSize={{ base: "2xl", md: "4xl" }}>AI解説生成システム</Heading>
            <Text color="brand.muted" fontSize={{ base: "sm", md: "md" }}>
              過去問PDFや画像から、AIが解説MarkdownとPDFを生成します。
            </Text>
          </Stack>

          <Box
            bg="whiteAlpha.900"
            border="1px solid"
            borderColor="brand.gold"
            borderRadius="2xl"
            boxShadow="0 20px 40px rgba(34, 21, 8, 0.08)"
            p={{ base: 6, md: 8 }}
          >
            <Grid templateColumns={{ base: "1fr", lg: "1.2fr 0.8fr" }} gap={8}>
              <GridItem>
                <VStack spacing={6} align="stretch">
                  <Box>
                    <Heading size="md" mb={2}>
                      新しいリクエスト
                    </Heading>
                    <Text color="brand.muted" fontSize="sm">
                      生成AIは誤答や不足が含まれる可能性があります。最終判断は必ず担当者が行ってください。
                    </Text>
                  </Box>

                  <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                    <FormControl>
                      <FormLabel>APIキー（任意）</FormLabel>
                      <Input
                        value={apiKey}
                        onChange={(event) => setApiKey(event.target.value)}
                        placeholder="Gemini API Key"
                        type="password"
                        autoComplete="new-password"
                        focusBorderColor="brand.gold"
                      />
                    </FormControl>
                    <FormControl>
                      <FormLabel>年度</FormLabel>
                      <Input
                        value={year}
                        onChange={(event) => setYear(event.target.value)}
                        placeholder="2024"
                        focusBorderColor="brand.gold"
                      />
                    </FormControl>
                    <FormControl>
                      <FormLabel>試験科目名</FormLabel>
                      <Input
                        value={subject}
                        onChange={(event) => setSubject(event.target.value)}
                        placeholder="生化学"
                        focusBorderColor="brand.gold"
                      />
                    </FormControl>
                    <FormControl>
                      <FormLabel>大学名</FormLabel>
                      <Input
                        value={university}
                        onChange={(event) => setUniversity(event.target.value)}
                        placeholder="東京大学"
                        focusBorderColor="brand.gold"
                      />
                    </FormControl>
                    <FormControl>
                      <FormLabel>試験問題作者名</FormLabel>
                      <Input
                        value={author}
                        onChange={(event) => setAuthor(event.target.value)}
                        placeholder="佐藤先生"
                        focusBorderColor="brand.gold"
                      />
                    </FormControl>
                    <FormControl>
                      <FormLabel>解説タイトル</FormLabel>
                      <Input
                        value={explanationName}
                        onChange={(event) => {
                          setExplanationName(event.target.value);
                          setUserEditedName(true);
                        }}
                        placeholder="2024_生化学_解答解説"
                        focusBorderColor="brand.gold"
                      />
                    </FormControl>
                  </SimpleGrid>

                  <FormControl>
                    <FormLabel>問題ファイル（PDF/JPEG/PNG）</FormLabel>
                    <Input
                      type="file"
                      accept="application/pdf,image/jpeg,image/png"
                      onChange={(event) => setInputFile(event.target.files?.[0] ?? null)}
                      focusBorderColor="brand.gold"
                    />
                  </FormControl>

                  <HStack spacing={4} align="center" flexWrap="wrap">
                    <Button
                      colorScheme="yellow"
                      bg="brand.gold"
                      color="brand.ink"
                      _hover={{ bg: "brand.goldDeep", color: "white" }}
                      onClick={onSubmit}
                      isDisabled={!canSubmit}
                    >
                      リクエストする
                    </Button>
                    {statusMessage ? (
                      <Text fontSize="sm" color="brand.muted">
                        {statusMessage}
                      </Text>
                    ) : null}
                    {errorMessage ? (
                      <Text fontSize="sm" color="red.700">
                        {errorMessage}
                      </Text>
                    ) : null}
                  </HStack>
                </VStack>
              </GridItem>

              <GridItem>
                <VStack spacing={4} align="stretch">
                  <Heading size="sm">TIPS</Heading>
                  <Box
                    bg="brand.bg"
                    border="1px solid"
                    borderColor="brand.gold"
                    borderRadius="xl"
                    p={4}
                    minH="140px"
                    display="flex"
                    alignItems="center"
                  >
                    <SlideFade in key={tipIndex} offsetY="8px">
                      <Text fontSize="sm" color="brand.ink">
                        {tips[tipIndex]}
                      </Text>
                    </SlideFade>
                  </Box>
                  <Divider borderColor="brand.gold" />
                  <Box>
                    <Text fontSize="sm" color="brand.muted" mb={2}>
                      現在のジョブはブラウザに保存されます。別端末からは見えません。
                    </Text>
                    <Text fontSize="xs" color="brand.muted">
                      進行中のジョブのみ自動で更新します。
                    </Text>
                  </Box>
                </VStack>
              </GridItem>
            </Grid>
          </Box>

          <Box>
            <HStack justify="space-between" mb={4} flexWrap="wrap">
              <Heading size="md">ジョブ一覧</Heading>
              <Button
                size="sm"
                variant="outline"
                borderColor="brand.gold"
                color="brand.ink"
                _hover={{ bg: "brand.gold", color: "brand.ink" }}
                onClick={refreshPendingJobs}
                isDisabled={pendingJobs.length === 0 || isRefreshing}
              >
                更新する
              </Button>
            </HStack>
            {jobs.length === 0 ? (
              <Box
                border="1px dashed"
                borderColor="brand.gold"
                borderRadius="xl"
                p={6}
                textAlign="center"
                color="brand.muted"
              >
                まだジョブがありません。上のフォームからリクエストしてください。
              </Box>
            ) : (
              <SimpleGrid columns={{ base: 1, lg: 2 }} spacing={5}>
                {jobs.map((job) => {
                  const label = statusLabels[job.status] ?? job.status;
                  const badgeStyle = statusBadgeStyles[job.status] ?? {
                    bg: "#EFE7DA",
                    color: "#6D5F4B"
                  };
                  const createdAtMs = new Date(job.createdAt).getTime();
                  const isStalled =
                    job.status === "generating_md" &&
                    Number.isFinite(createdAtMs) &&
                    Date.now() - createdAtMs >= 30 * 60 * 1000;
                  const isDownloadable = job.status === "done";
                  const isRetryable = job.status === "failed_to_convert" || isStalled;
                  const isDownloading = downloadingJobId === job.jobId;

                  return (
                    <Box
                      key={job.jobId}
                      position="relative"
                      bg="white"
                      border="1px solid"
                      borderColor="brand.gold"
                      borderRadius="xl"
                      p={5}
                      boxShadow="0 12px 24px rgba(28, 18, 7, 0.08)"
                    >
                      {isDownloading ? (
                        <Box
                          position="absolute"
                          inset={0}
                          bg="rgba(247, 244, 238, 0.72)"
                          borderRadius="xl"
                          display="flex"
                          alignItems="center"
                          justifyContent="center"
                          flexDirection="column"
                          gap={4}
                          zIndex={1}
                        >
                          <Text fontSize="sm" color="brand.ink">
                            ダウンロード中...
                          </Text>
                          <Box
                            position="relative"
                            w="70%"
                            h="6px"
                            bg="rgba(201, 161, 74, 0.2)"
                            borderRadius="999px"
                            overflow="hidden"
                          >
                            <Box
                              position="absolute"
                              top={0}
                              left={0}
                              w="100%"
                              h="100%"
                              bg="brand.gold"
                              transformOrigin="left"
                              animation={`${loadingBar} 2.2s ease-in-out infinite`}
                            />
                          </Box>
                          <Box
                            w="22px"
                            h="22px"
                            bg="brand.goldDeep"
                            animation={`${shapeShift} 2.6s ease-in-out infinite`}
                          />
                        </Box>
                      ) : null}

                      <VStack spacing={3} align="stretch" opacity={isDownloading ? 0.4 : 1}>
                        <HStack justify="space-between" flexWrap="wrap">
                          <Text fontWeight="600">{job.explanationName}</Text>
                          <Badge bg={badgeStyle.bg} color={badgeStyle.color} borderRadius="full" px={3}>
                            {label}
                          </Badge>
                        </HStack>
                        <Text fontSize="sm" color="brand.muted">
                          job_id: {job.jobId}
                        </Text>
                        <Text fontSize="xs" color="brand.muted">
                          作成: {formatDate(job.createdAt)} / 更新: {formatDate(job.updatedAt)}
                        </Text>
                        {job.message ? (
                          <Text fontSize="sm" color="brand.muted">
                            {job.message}
                          </Text>
                        ) : null}
                        {job.error ? (
                          <Text fontSize="sm" color="red.700">
                            {job.error}
                          </Text>
                        ) : null}
                        <HStack spacing={3} flexWrap="wrap">
                          {isDownloadable ? (
                            <Button
                              alignSelf="flex-start"
                              size="sm"
                              bg="brand.gold"
                              color="brand.ink"
                              _hover={{ bg: "brand.goldDeep", color: "white" }}
                              onClick={() => handleDownload(job.jobId)}
                            >
                              ダウンロードする
                            </Button>
                          ) : null}
                          {isRetryable ? (
                            <>
                              <Text fontSize="xs" color="brand.muted">
                                エラーが発生したかも？
                              </Text>
                              <Button
                                alignSelf="flex-start"
                                size="sm"
                                variant="outline"
                                borderColor="brand.gold"
                                color="brand.ink"
                                _hover={{ bg: "brand.gold", color: "brand.ink" }}
                                onClick={() => openRetryModal(job)}
                              >
                                もう一度試す
                              </Button>
                            </>
                          ) : null}
                        </HStack>
                      </VStack>
                    </Box>
                  );
                })}
              </SimpleGrid>
            )}
          </Box>
        </VStack>
      </Container>

      <Modal isOpen={isRetryOpen} onClose={closeRetryModal} size="xl">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>もう一度試す</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <VStack spacing={4} align="stretch">
              <Text fontSize="sm" color="brand.muted">
                前回の入力をできるだけ引き継いでいます。必要な箇所だけ修正してください。
              </Text>
              <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                <FormControl>
                  <FormLabel>APIキー（任意）</FormLabel>
                  <Input
                    value={retryApiKey}
                    onChange={(event) => setRetryApiKey(event.target.value)}
                    placeholder="Gemini API Key"
                    focusBorderColor="brand.gold"
                    type="password"
                    autoComplete="new-password"
                  />
                </FormControl>
                <FormControl>
                  <FormLabel>年度</FormLabel>
                  <Input
                    value={retryYear}
                    onChange={(event) => setRetryYear(event.target.value)}
                    placeholder="2024"
                    focusBorderColor="brand.gold"
                  />
                </FormControl>
                <FormControl>
                  <FormLabel>試験科目名</FormLabel>
                  <Input
                    value={retrySubject}
                    onChange={(event) => setRetrySubject(event.target.value)}
                    placeholder="生化学"
                    focusBorderColor="brand.gold"
                  />
                </FormControl>
                <FormControl>
                  <FormLabel>大学名</FormLabel>
                  <Input
                    value={retryUniversity}
                    onChange={(event) => setRetryUniversity(event.target.value)}
                    placeholder="東京大学"
                    focusBorderColor="brand.gold"
                  />
                </FormControl>
                <FormControl>
                  <FormLabel>試験問題作者名</FormLabel>
                  <Input
                    value={retryAuthor}
                    onChange={(event) => setRetryAuthor(event.target.value)}
                    placeholder="佐藤先生"
                    focusBorderColor="brand.gold"
                  />
                </FormControl>
                <FormControl>
                  <FormLabel>解説タイトル</FormLabel>
                  <Input
                    value={retryExplanationName}
                    onChange={(event) => {
                      setRetryExplanationName(event.target.value);
                      setRetryUserEditedName(true);
                    }}
                    placeholder="2024_生化学_解答解説"
                    focusBorderColor="brand.gold"
                  />
                </FormControl>
              </SimpleGrid>
              <FormControl>
                <FormLabel>問題ファイル（PDF/JPEG/PNG）</FormLabel>
                <Input
                  type="file"
                  accept="application/pdf,image/jpeg,image/png"
                  onChange={(event) => setRetryFile(event.target.files?.[0] ?? null)}
                  focusBorderColor="brand.gold"
                />
              </FormControl>
              {retryJob ? (
                <Text fontSize="xs" color="brand.muted">
                  対象ジョブ: {retryJob.jobId}
                </Text>
              ) : null}
            </VStack>
          </ModalBody>
          <ModalFooter>
            <HStack spacing={3}>
              <Button variant="ghost" onClick={closeRetryModal}>
                閉じる
              </Button>
              <Button
                bg="brand.gold"
                color="brand.ink"
                _hover={{ bg: "brand.goldDeep", color: "white" }}
                onClick={onRetrySubmit}
                isDisabled={!retryCanSubmit}
              >
                もう一度試す
              </Button>
            </HStack>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </Box>
  );
}
